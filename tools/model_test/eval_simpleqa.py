"""
tools/eval_simpleqa.py

SimpleQAなどの標準データセットに基づくエージェント評価・集計スクリプト。
モデル/エージェントの正確性 (Correct)、ハルシネーション (Incorrect)、回答拒否 (Abstain) を判定・集計する。
"""

import json
import logging
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("eval_simpleqa")

# 回答辞退/不明を示す代表的なキーワード
ABSTAIN_KEYWORDS = ["分かりません", "不明", "知らん", "情報がありません", "答えることができません", "unknown", "don't know", "i don't know"]

def get_default_model_from_config(root_dir: Path = Path(".")) -> str:
    """opencode.json から pm エージェント設定モデル（または default モデル）を動的に読み込む"""
    opencode_json = root_dir / "opencode.json"
    if opencode_json.exists():
        try:
            config = json.loads(opencode_json.read_text(encoding="utf-8"))
            # 1. default_agent (例: pm) のモデルを取得
            default_agent = config.get("default_agent", "pm")
            agent_cfg = config.get("agent", {}).get(default_agent, {})
            model_name = agent_cfg.get("model") or config.get("model")

            if model_name:
                # "ollama/gemma4-12b-it-Q4_K_M:latest" 形式からモデル名を抽出
                if "/" in model_name:
                    model_name = model_name.split("/", 1)[1]
                return model_name
        except Exception as e:
            logger.warning(f"opencode.json のパースに失敗しました: {e}")

    # フォールバック
    return "gemma4-12b-it-Q4_K_M:latest"

def call_ollama_gemma4(prompt: str, model_name: str = None) -> Tuple[str, str]:
    """Ollama API (http://localhost:11434/api/generate) を使用して推論を行い、(最終回答, 内部思考/Reasoning) のタプルを返す"""
    if not model_name:
        model_name = get_default_model_from_config()

    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            if resp.status == 200:
                result = json.loads(resp.read().decode("utf-8"))
                raw_response = result.get("response", "") or result.get("content", "")
                thinking = result.get("thinking", "")

                # <think>...</think> タグが含まれている場合は分離
                import re
                think_match = re.search(r"<think>(.*?)</think>", raw_response, re.DOTALL)
                if think_match:
                    thinking = (thinking + "\n" + think_match.group(1)).strip()
                    raw_response = re.sub(r"<think>.*?</think>", "", raw_response, flags=re.DOTALL).strip()
                elif "</think>" in raw_response:
                    parts = raw_response.split("</think>", 1)
                    thinking = (thinking + "\n" + parts[0].replace("<think>", "")).strip()
                    raw_response = parts[1].strip()

                output_text = raw_response.strip()
                if not output_text and thinking:
                    # 思考プロセスのみで回答部分が空の場合のフォールバック
                    output_text = thinking.splitlines()[-1].strip()

                final_text = output_text if output_text else "分かりません"
                return final_text, thinking
    except Exception as e:
        logger.warning(f"Ollama API 呼出エラー ({model_name}): {e}")
    return "分かりません", ""

class SimpleQAEvaluator:
    def __init__(self, dataset_path: Path):
        self.dataset_path = dataset_path
        if not self.dataset_path.exists():
            raise FileNotFoundError(f"データセットファイルが見つかりません: {dataset_path}")
        self.data = json.loads(self.dataset_path.read_text(encoding="utf-8"))

    def evaluate_response(self, target: str, response: str, allow_abstain: bool = False, aliases: List[str] = None) -> str:
        """
        モデルのレスポンスを評価し、'correct', 'incorrect', 'abstain' のいずれかを返す。
        aliases (同義語・別名リスト) が指定されている場合、それらのいずれかが含まれていれば正解と判定する。
        """
        response_lower = response.strip().lower()
        target_lower = target.strip().lower()
        aliases_lower = [a.strip().lower() for a in (aliases or [])]

        # 1. 回答拒否 (Abstain) の判定
        is_abstain = any(kw in response_lower for kw in ABSTAIN_KEYWORDS)
        
        # ターゲットまたは同義語自体が Abstain/不明 を要求している場合
        if allow_abstain or any(kw in target_lower for kw in ABSTAIN_KEYWORDS):
            if is_abstain or target_lower in response_lower or any(a in response_lower for a in aliases_lower):
                return "correct"

        if is_abstain:
            return "abstain"

        # 2. 正解 (Correct) の判定（ターゲットまたは同義語文字列が回答に含まれているか）
        if target_lower in response_lower or any(a in response_lower for a in aliases_lower):
            return "correct"

        # 3. 誤答 / ハルシネーション (Incorrect)
        return "incorrect"

    def run_eval(self, mock_responses: Dict[str, str] = None, use_llm: bool = False, agent_name: str = "coder", model_name: str = None) -> Dict[str, Any]:
        """
        全問題に対して評価を実行する。
        use_llmがTrueの場合は opencode.json 設定モデル (Ollama / AgentClient) でリアルタイムに推論を行う。
        """
        if not model_name:
            model_name = get_default_model_from_config()

        results = []
        counts = {"correct": 0, "incorrect": 0, "abstain": 0}

        agent_client = None
        if use_llm:
            logger.info(f"実LLM ({model_name}) による全20件の推論測定を開始します...")
            try:
                from tools.agent_client import AgentClient
                agent_client = AgentClient()
            except Exception:
                agent_client = None

        for idx, item in enumerate(self.data, 1):
            item_id = item.get("id")
            problem = item.get("problem")
            target = item.get("target")
            aliases = item.get("aliases", [])
            allow_abstain = item.get("allow_abstain", False)

            response = ""
            reasoning = ""
            if use_llm:
                prompt = f"以下の質問に簡潔かつ事実に基づき一言または1文で回答してください。\n質問: {problem}\n分からない場合は『分かりません』と回答してください。"
                logger.info(f"[{idx}/{len(self.data)}] 推論実行中 ({item_id}): {problem}")
                
                # 1. Ollama API による直接呼出を試行 (最終回答と内部思考を分離)
                response, reasoning = call_ollama_gemma4(prompt, model_name=model_name)
                
                # 2. 失敗した場合は AgentClient を試行
                if response == "分かりません" and agent_client:
                    try:
                        resp = agent_client.call_agent(agent_name, prompt)
                        if resp and resp.success and resp.raw_output:
                            response = resp.raw_output
                    except Exception:
                        pass
            elif mock_responses and item_id in mock_responses:
                response = mock_responses[item_id]
            else:
                # デフォルトのシミュレーション回答
                response = target if "火星" not in problem else "分かりません"

            status = self.evaluate_response(target, response, allow_abstain=allow_abstain, aliases=aliases)
            counts[status] += 1

            detail_item = {
                "id": item_id,
                "problem": problem,
                "target": target,
                "response": response,
                "status": status
            }
            if reasoning:
                detail_item["reasoning"] = reasoning

            results.append(detail_item)

        total = len(self.data)
        summary = {
            "total": total,
            "counts": counts,
            "rates": {
                "correct_rate": round(counts["correct"] / total * 100, 2) if total > 0 else 0,
                "incorrect_rate": round(counts["incorrect"] / total * 100, 2) if total > 0 else 0,
                "abstain_rate": round(counts["abstain"] / total * 100, 2) if total > 0 else 0
            },
            "details": results
        }
        return summary

    def print_report(self, summary: Dict[str, Any], verbose: bool = False):
        print("\n========================================")
        print(" SimpleQA Evaluation Summary Report")
        print("========================================")
        print(f"Total Questions : {summary['total']}")
        print(f"- Correct       : {summary['counts']['correct']} ({summary['rates']['correct_rate']}%)")
        print(f"- Incorrect     : {summary['counts']['incorrect']} ({summary['rates']['incorrect_rate']}%)")
        print(f"- Abstain       : {summary['counts']['abstain']} ({summary['rates']['abstain_rate']}%)")
        print("========================================")

        if verbose and "details" in summary:
            print("\n----------------------------------------")
            print(" Per-Question Detailed Results")
            print("----------------------------------------")
            for item in summary["details"]:
                status_icon = "✓ [CORRECT]" if item["status"] == "correct" else ("? [ABSTAIN]" if item["status"] == "abstain" else "✗ [INCORRECT]")
                print(f"\nID       : {item['id']} {status_icon}")
                print(f"Question : {item['problem']}")
                print(f"Target   : {item['target']}")
                print(f"Response : {item['response']}")
                if "reasoning" in item and item["reasoning"]:
                    reasoning_snippet = item['reasoning'].replace('\n', ' ')
                    if len(reasoning_snippet) > 120:
                        reasoning_snippet = reasoning_snippet[:120] + "..."
                    print(f"Reasoning: {reasoning_snippet}")
            print("----------------------------------------\n")
        else:
            print()


    def save_eval_history(self, summary: Dict[str, Any], model_name: str, output_path: Optional[Path] = None):
        """評価結果ログを JSON ファイルに保存・追加記録する"""
        from datetime import datetime

        if output_path is None:
            output_dir = Path("tools/.cache")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / "eval_history.json"
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)

        record = {
            "timestamp": datetime.now().isoformat(),
            "model": model_name,
            "dataset": str(self.dataset_path),
            "summary": {
                "total": summary["total"],
                "counts": summary["counts"],
                "rates": summary["rates"]
            },
            "details": summary.get("details", [])
        }

        history = []
        if output_path.exists():
            try:
                history = json.loads(output_path.read_text(encoding="utf-8"))
                if not isinstance(history, list):
                    history = [history]
            except Exception:
                history = []

        history.append(record)

        try:
            output_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"✓ 評価ログを外部JSONファイルに保存しました: {output_path}")
        except Exception as e:
            logger.error(f"評価ログの保存に失敗しました: {e}")


def main():
    default_model = get_default_model_from_config()
    parser = argparse.ArgumentParser(description="SimpleQA データセット評価スクリプト")
    parser.add_argument("--dataset", type=str, default="tests/datasets/simpleqa_sample.json", help="データセットファイルパス")
    parser.add_argument("--use-llm", action="store_true", default=False, help="実際の LLM (opencode.json 設定) を呼び出して評価する")
    parser.add_argument("--model", type=str, default=default_model, help=f"評価に使用するモデル名 (デフォルト: {default_model})")
    parser.add_argument("--agent", type=str, default="pm", help="評価対象のエージェント名 (pm/coder/executor等)")
    parser.add_argument("--output-json", action="store_true", default=False, help="評価結果を外部JSONファイル(tools/.cache/eval_history.json)に保存する")
    parser.add_argument("--output-path", type=str, default=None, help="評価結果JSONログの出力先カスタムパス")
    parser.add_argument("-v", "--verbose", action="store_true", default=False, help="問題ごとの評価詳細（質問・正解・生応答）を出力する")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    evaluator = SimpleQAEvaluator(dataset_path)
    summary = evaluator.run_eval(use_llm=args.use_llm, agent_name=args.agent, model_name=args.model)
    evaluator.print_report(summary, verbose=args.verbose)

    if args.output_json or args.output_path:
        out_p = Path(args.output_path) if args.output_path else None
        evaluator.save_eval_history(summary, model_name=args.model, output_path=out_p)


if __name__ == "__main__":
    main()
