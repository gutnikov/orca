import { describe, expect, it } from "vitest"
import { parseUnifiedDiff } from "./diff-parser"

describe("parseUnifiedDiff", () => {
  it("parses a simple hunk with correct line numbers", () => {
    const diff = [
      "diff --git a/f.txt b/f.txt",
      "index 111..222 100644",
      "--- a/f.txt",
      "+++ b/f.txt",
      "@@ -1,3 +1,3 @@",
      " one",
      "-two",
      "+TWO",
      " three",
    ].join("\n")

    const hunks = parseUnifiedDiff(diff)
    expect(hunks).toHaveLength(1)
    expect(hunks[0].rows).toEqual([
      { type: "context", oldLine: 1, newLine: 1, text: "one" },
      { type: "removed", oldLine: 2, newLine: null, text: "two" },
      { type: "added", oldLine: null, newLine: 2, text: "TWO" },
      { type: "context", oldLine: 3, newLine: 3, text: "three" },
    ])
  })

  it("keeps removed lines whose content starts with -- and does not shift later line numbers", () => {
    // "--- drop me" is a removed line whose content is "-- drop me"
    // (e.g. a SQL comment); it must not be mistaken for a file header.
    const diff = [
      "--- a/q.sql",
      "+++ b/q.sql",
      "@@ -1,3 +1,2 @@",
      " SELECT 1;",
      "--- drop me",
      " SELECT 2;",
    ].join("\n")

    const hunks = parseUnifiedDiff(diff)
    expect(hunks).toHaveLength(1)
    expect(hunks[0].rows).toEqual([
      { type: "context", oldLine: 1, newLine: 1, text: "SELECT 1;" },
      { type: "removed", oldLine: 2, newLine: null, text: "-- drop me" },
      { type: "context", oldLine: 3, newLine: 2, text: "SELECT 2;" },
    ])
  })

  it("keeps added lines whose content starts with ++ and does not shift later line numbers", () => {
    const diff = [
      "--- a/f.c",
      "+++ b/f.c",
      "@@ -1,2 +1,3 @@",
      " int i = 0;",
      "+++i;",
      " return i;",
    ].join("\n")

    const hunks = parseUnifiedDiff(diff)
    expect(hunks).toHaveLength(1)
    expect(hunks[0].rows).toEqual([
      { type: "context", oldLine: 1, newLine: 1, text: "int i = 0;" },
      { type: "added", oldLine: null, newLine: 2, text: "++i;" },
      { type: "context", oldLine: 2, newLine: 3, text: "return i;" },
    ])
  })

  it("ignores '\\ No newline at end of file' without bumping either cursor", () => {
    const diff = [
      "--- a/f.txt",
      "+++ b/f.txt",
      "@@ -1,2 +1,2 @@",
      " one",
      "-two",
      "\\ No newline at end of file",
      "+two!",
      "\\ No newline at end of file",
    ].join("\n")

    const hunks = parseUnifiedDiff(diff)
    expect(hunks).toHaveLength(1)
    expect(hunks[0].rows).toEqual([
      { type: "context", oldLine: 1, newLine: 1, text: "one" },
      { type: "removed", oldLine: 2, newLine: null, text: "two" },
      { type: "added", oldLine: null, newLine: 2, text: "two!" },
    ])
  })

  it("parses multiple hunks and ignores lines between them", () => {
    const diff = [
      "@@ -1,1 +1,1 @@",
      "-a",
      "+A",
      "@@ -10,2 +10,1 @@",
      " ctx",
      "-gone",
    ].join("\n")

    const hunks = parseUnifiedDiff(diff)
    expect(hunks).toHaveLength(2)
    expect(hunks[0].rows).toEqual([
      { type: "removed", oldLine: 1, newLine: null, text: "a" },
      { type: "added", oldLine: null, newLine: 1, text: "A" },
    ])
    expect(hunks[1].rows).toEqual([
      { type: "context", oldLine: 10, newLine: 10, text: "ctx" },
      { type: "removed", oldLine: 11, newLine: null, text: "gone" },
    ])
  })

  it("does not treat the next file's headers in a multi-file diff as content", () => {
    const diff = [
      "--- a/one.txt",
      "+++ b/one.txt",
      "@@ -1,1 +1,1 @@",
      "-old",
      "+new",
      "diff --git a/two.txt b/two.txt",
      "--- a/two.txt",
      "+++ b/two.txt",
      "@@ -5,1 +5,1 @@",
      "-x",
      "+y",
    ].join("\n")

    const hunks = parseUnifiedDiff(diff)
    expect(hunks).toHaveLength(2)
    expect(hunks[0].rows).toEqual([
      { type: "removed", oldLine: 1, newLine: null, text: "old" },
      { type: "added", oldLine: null, newLine: 1, text: "new" },
    ])
    expect(hunks[1].rows).toEqual([
      { type: "removed", oldLine: 5, newLine: null, text: "x" },
      { type: "added", oldLine: null, newLine: 5, text: "y" },
    ])
  })
})
