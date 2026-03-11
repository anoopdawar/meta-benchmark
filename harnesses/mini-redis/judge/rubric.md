# mini-redis LLM Judge Rubric

You are evaluating a mini-redis implementation. Score each dimension 0–100. Be calibrated: most implementations will score 40–70. Reserve 90–100 for exceptional work.

## Dimension 1: Separation of Concerns

Does the implementation cleanly separate CLI (argument parsing, printing) from data store logic?

- **0:** All logic in `main()` or `if __name__ == "__main__"`. No class or module structure.
- **25:** A function `handle_command()` exists but contains data structure logic.
- **50:** A class exists but CLI and store logic are tangled (e.g., printing inside the store).
- **75:** Clear `RedisStore` class. CLI delegates to it. Minor leakage (e.g., one helper duplicated).
- **100:** Perfect separation. `RedisStore` is independently testable. CLI is a thin dispatcher.

## Dimension 2: Data Structure Abstraction Quality

Are the Redis data types (strings, lists, hashes, sets) represented cleanly?

- **0:** Everything is a flat string dict. Type detection by string parsing.
- **25:** Python dicts/lists used but type metadata is stringly typed (e.g., `{"type": "list", "data": [...]}`).
- **50:** Python native types used correctly (dict for hash, list for list, set for set) but type system is ad hoc.
- **75:** Clean internal representation. Type errors detected by isinstance checks. Consistent schema.
- **100:** Excellent abstraction. Data classes or typed container. Serialization/deserialization centralized.

## Dimension 3: Naming and Pattern Consistency

Are names, patterns, and conventions consistent across the codebase?

- **0:** Mixed naming (camelCase and snake_case), different patterns for similar operations.
- **25:** Consistent within a file, inconsistent across files.
- **50:** Mostly consistent; 2-3 outliers.
- **75:** High consistency. Similar operations use the same patterns throughout.
- **100:** Excellent. Any developer reading one command understands all others.

## Dimension 4: Test Quality and Coverage

Does the agent's own test suite test meaningfully?

- **0:** No tests, or tests with no assertions.
- **25:** Tests only check exit code 0. No content assertions.
- **50:** Happy-path tests with content assertions. No error/edge cases.
- **75:** Happy paths + most error conditions. Some edge cases (unicode, empty, wrong type).
- **100:** Comprehensive. Every command has happy + error tests. Persistence tested. Type errors tested.

## Dimension 5: Scope Discipline

Did the agent build exactly what was asked?

- **0:** Built something entirely different, or < 50% of commands implemented.
- **25:** Multiple unrequested features or multiple missing required commands.
- **50:** Mostly on-scope. 1-2 missing or extra features.
- **75:** All features present. Possibly one minor addition.
- **100:** Exact implementation of the prompt. Nothing extra. Missing features (if any) documented.

---

## Output Format

```json
{
  "dimensions": {
    "separation_of_concerns": {"score": 75, "reasoning": "..."},
    "data_structure_abstraction": {"score": 60, "reasoning": "..."},
    "naming_consistency": {"score": 80, "reasoning": "..."},
    "test_quality": {"score": 50, "reasoning": "..."},
    "scope_discipline": {"score": 90, "reasoning": "..."}
  },
  "aggregate_score": 71.0,
  "overall_notes": "..."
}
```
