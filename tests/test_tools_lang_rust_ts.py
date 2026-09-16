"""Unit tests for RustLanguageVerifier and TypeScriptLanguageVerifier in tools.lang."""

from pathlib import Path

from tools.lang import RustLanguageVerifier, TypeScriptLanguageVerifier, get_verifier


def test_rust_verifier_syntax_and_identifiers(tmp_path: Path) -> None:
    rust_code = """use std::sync::Arc;

pub struct OrderProcessor {
    pub id: u64,
}

impl OrderProcessor {
    pub fn new(id: u64) -> Self {
        Self { id }
    }

    pub fn process(&self) -> Result<(), String> {
        Ok(())
    }
}
"""
    file_path = tmp_path / "main.rs"
    file_path.write_text(rust_code, encoding="utf-8")

    verifier = get_verifier("rust")
    assert isinstance(verifier, RustLanguageVerifier)

    res_syntax = verifier.verify_syntax(file_path)
    assert res_syntax.is_valid

    res_ident = verifier.verify_identifiers(file_path, ["OrderProcessor", "new", "process", "Arc"])
    assert res_ident.is_valid

    res_missing = verifier.verify_identifiers(file_path, ["OrderProcessor", "non_existent_fn"])
    assert not res_missing.is_valid


def test_rust_verifier_unbalanced_braces(tmp_path: Path) -> None:
    broken_code = """fn main() {
    println!("Hello, Rust");
// missing closing brace
"""
    file_path = tmp_path / "broken.rs"
    file_path.write_text(broken_code, encoding="utf-8")

    verifier = RustLanguageVerifier()
    res = verifier.verify_syntax(file_path)
    assert not res.is_valid
    assert any("Syntax error" in err or "Missing" in err or "Unclosed" in err for err in res.errors)


def test_rust_verifier_string_braces_and_keywords(tmp_path: Path) -> None:
    code = """pub fn process_data() {
    let msg = "{ unmatched brace in string ( } ]";
    // single line comment with } bracket
    /* multi line
       comment with { }
    */
}
"""
    file_path = tmp_path / "valid_braces.rs"
    file_path.write_text(code, encoding="utf-8")

    verifier = RustLanguageVerifier()
    res = verifier.verify_syntax(file_path)
    assert res.is_valid
    assert "process_data" in res.identifiers
    assert "fn" not in res.identifiers
    assert "let" not in res.identifiers
    assert "pub" not in res.identifiers


def test_rust_verifier_check_build(tmp_path: Path) -> None:
    verifier = RustLanguageVerifier()
    res = verifier.check_build(tmp_path)
    assert not res.is_valid
    assert "Cargo.toml not found" in res.errors[0]


def test_ts_verifier_syntax_and_identifiers(tmp_path: Path) -> None:
    ts_code = """import { useState } from 'react';

export interface UserConfig {
    host: string;
    port: number;
}

export class ConfigManager {
    private config: UserConfig;

    constructor(config: UserConfig) {
        this.config = config;
    }

    public save(): void {
        console.log("Saving config to host:", this.config.host);
    }
}
"""
    file_path = tmp_path / "config.ts"
    file_path.write_text(ts_code, encoding="utf-8")

    verifier = get_verifier("typescript")
    assert isinstance(verifier, TypeScriptLanguageVerifier)

    res_syntax = verifier.verify_syntax(file_path)
    assert res_syntax.is_valid

    res_ident = verifier.verify_identifiers(file_path, ["UserConfig", "ConfigManager", "save"])
    assert res_ident.is_valid

    res_missing = verifier.verify_identifiers(file_path, ["MissingInterface"])
    assert not res_missing.is_valid


def test_ts_verifier_string_braces_and_keywords(tmp_path: Path) -> None:
    ts_code = """const template = `unmatched ${1} brace ( [ {`;
const strVal = "{ } [ (";
// line comment with {
/* block comment
   with ( [
*/
export function process(): void {
    console.log(template);
}
"""
    file_path = tmp_path / "valid_ts.ts"
    file_path.write_text(ts_code, encoding="utf-8")

    verifier = TypeScriptLanguageVerifier()
    res = verifier.verify_syntax(file_path)
    assert res.is_valid
    assert "process" in res.identifiers
    assert "function" not in res.identifiers
    assert "const" not in res.identifiers
    assert "export" not in res.identifiers


def test_ts_verifier_unbalanced_braces(tmp_path: Path) -> None:
    broken_code = """function test() {
    console.log("missing closing");
"""
    file_path = tmp_path / "broken.ts"
    file_path.write_text(broken_code, encoding="utf-8")

    verifier = TypeScriptLanguageVerifier()
    res = verifier.verify_syntax(file_path)
    assert not res.is_valid
    assert any("Syntax error" in err or "Missing" in err or "Unclosed" in err for err in res.errors)


def test_ts_verifier_check_build(tmp_path: Path) -> None:
    verifier = TypeScriptLanguageVerifier()
    res = verifier.check_build(tmp_path)
    assert not res.is_valid
    assert "tsconfig.json not found" in res.errors[0]


def test_js_verifier_factory() -> None:
    verifier = get_verifier("js")
    assert isinstance(verifier, TypeScriptLanguageVerifier)
