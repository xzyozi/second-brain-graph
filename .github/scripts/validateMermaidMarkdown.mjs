#!/usr/bin/env node

import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join, relative, resolve } from "node:path";

const MERMAID_CLI_PACKAGE = "@mermaid-js/mermaid-cli@11.4.2";
const EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";
const REPOSITORY_ROOT = resolve(import.meta.dirname, "..", "..");
const DOCS_DIRECTORY = join(REPOSITORY_ROOT, "docs");

/**
 * Parse the supported command-line options.
 *
 * Returns:
 *     Object containing all-mode or the base and head Git revisions.
 *
 * Raises:
 *     Error: If the arguments do not describe a supported invocation.
 */
const parseArguments = () => {
    const argumentsList = process.argv.slice(2);
    if (argumentsList.length === 1 && argumentsList[0] === "--all") {
        return { all: true };
    }

    const baseIndex = argumentsList.indexOf("--base");
    const headIndex = argumentsList.indexOf("--head");
    if (baseIndex < 0 || headIndex < 0 || !argumentsList[baseIndex + 1] || !argumentsList[headIndex + 1]) {
        throw new Error("Usage: --all or --base <commit> --head <commit>");
    }

    return { all: false, base: argumentsList[baseIndex + 1], head: argumentsList[headIndex + 1] };
};

/**
 * Convert an initial-push SHA to the Git empty tree SHA.
 *
 * Args:
 *     revision: Git revision supplied by GitHub Actions.
 *
 * Returns:
 *     A revision that is valid as the left side of git diff.
 */
const normalizeBaseRevision = (revision) => (revision === "0".repeat(40) ? EMPTY_TREE_SHA : revision);

/**
 * Run a Git command in the repository and return its text output.
 *
 * Args:
 *     argumentsList: Arguments to pass to Git.
 *
 * Returns:
 *     Standard output from Git, decoded as UTF-8.
 */
const runGit = (argumentsList) => execFileSync("git", argumentsList, { cwd: REPOSITORY_ROOT, encoding: "utf8" });

/**
 * Collect Markdown files changed between two revisions.
 *
 * Args:
 *     base: Comparison base revision.
 *     head: Comparison head revision.
 *
 * Returns:
 *     Repository-relative Markdown paths under docs.
 */
const collectChangedMarkdownFiles = (base, head) => runGit([
    "diff", "--name-only", "--diff-filter=ACMR", normalizeBaseRevision(base), head, "--", "docs",
]).split(/\r?\n/).filter((filePath) => filePath.endsWith(".md"));
/**
 * Recursively collect every Markdown file under docs.
 *
 * Args:
 *     directory: Absolute directory to search.
 *
 * Returns:
 *     Repository-relative Markdown paths.
 */
const collectAllMarkdownFiles = (directory = DOCS_DIRECTORY) => readdirSync(directory, { withFileTypes: true }).flatMap(
    (entry) => {
        const entryPath = join(directory, entry.name);
        if (entry.isDirectory()) {
            return collectAllMarkdownFiles(entryPath);
        }
        return entry.isFile() && entry.name.endsWith(".md") ? [relative(REPOSITORY_ROOT, entryPath)] : [];
    },
);

/**
 * Extract Mermaid blocks and their source locations from a Markdown file.
 *
 * Args:
 *     filePath: Repository-relative Markdown path.
 *
 * Returns:
 *     Mermaid source, block number, and opening-fence line for every block.
 *
 * Raises:
 *     Error: If a Mermaid fence is not closed or contains no diagram source.
 */
const extractMermaidBlocks = (filePath) => {
    const lines = readFileSync(join(REPOSITORY_ROOT, filePath), "utf8").split(/\r?\n/);
    const blocks = [];
    let content = [];
    let startLine = null;

    lines.forEach((line, lineIndex) => {
        if (startLine === null && /^\s*```mermaid\s*$/.test(line)) {
            startLine = lineIndex + 1;
            content = [];
        } else if (startLine !== null && /^\s*```\s*$/.test(line)) {
            if (content.join("\n").trim().length === 0) {
                throw new Error(`${filePath}:${startLine}: Mermaid block is empty.`);
            }
            blocks.push({ content: content.join("\n"), number: blocks.length + 1, startLine });
            startLine = null;
        } else if (startLine !== null) {
            content.push(line);
        }
    });

    if (startLine !== null) {
        throw new Error(`${filePath}:${startLine}: Mermaid fence is not closed.`);
    }
    return blocks;
};

/**
 * Render one Mermaid block and report its original Markdown location on failure.
 *
 * Args:
 *     filePath: Repository-relative Markdown path.
 *     block: Mermaid source and location metadata.
 *     temporaryDirectory: Directory for ephemeral rendering files.
 *
 * Returns:
 *     Nothing.
 *
 * Raises:
 *     Error: If Mermaid CLI cannot render the block.
 */
const renderBlock = (filePath, block, temporaryDirectory) => {
    const fileStem = `${basename(filePath, ".md")}-${block.number}`;
    const inputPath = join(temporaryDirectory, `${fileStem}.mmd`);
    const outputPath = join(temporaryDirectory, `${fileStem}.svg`);
    writeFileSync(inputPath, block.content, "utf8");

    const npxCommand = process.platform === "win32" ? "npx.cmd" : "npx";
    const result = spawnSync(npxCommand, [
        "--yes", "--package", MERMAID_CLI_PACKAGE, "mmdc", "--input", inputPath, "--output", outputPath,
    ], { cwd: REPOSITORY_ROOT, encoding: "utf8" });
    if (result.status !== 0) {
        const details = [result.stdout, result.stderr].filter(Boolean).join("\n").trim();
        throw new Error(`${filePath}:${block.startLine}: Mermaid block ${block.number} could not be rendered.\n${details}`);
    }
};

/**
 * Validate Mermaid blocks from the selected Markdown files.
 *
 * Args:
 *     filePaths: Repository-relative Markdown paths.
 *
 * Returns:
 *     Nothing.
 *
 * Raises:
 *     Error: If one or more blocks cannot be validated.
 */
const validateMermaid = (filePaths) => {
    if (filePaths.length === 0) {
        console.log("No changed Markdown files under docs; Mermaid validation skipped.");
        return;
    }

    const temporaryDirectory = mkdtempSync(join(tmpdir(), "mermaid-validation-"));
    const errors = [];
    let diagramCount = 0;
    try {
        filePaths.forEach((filePath) => {
            try {
                const blocks = extractMermaidBlocks(filePath);
                blocks.forEach((block) => {
                    diagramCount += 1;
                    renderBlock(filePath, block, temporaryDirectory);
                });
            } catch (error) {
                errors.push(error instanceof Error ? error.message : String(error));
            }
        });
    } finally {
        rmSync(temporaryDirectory, { force: true, recursive: true });
    }

    if (errors.length > 0) {
        throw new Error(`Mermaid validation failed:\n\n${errors.join("\n\n")}`);
    }
    console.log(`Validated ${diagramCount} Mermaid diagram(s) in ${filePaths.length} Markdown file(s).`);
};

try {
    const options = parseArguments();
    const files = options.all ? collectAllMarkdownFiles() : collectChangedMarkdownFiles(options.base, options.head);
    validateMermaid(files);
} catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
}
