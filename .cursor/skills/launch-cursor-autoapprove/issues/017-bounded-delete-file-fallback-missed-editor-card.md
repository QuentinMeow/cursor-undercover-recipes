---
id: 017
title: Bounded delete-file fallback missed the preserved editor-surface fixture
status: resolved
severity: high
root_cause: The renderer-freeze fix limited delete-file fallback discovery to virtual transcript rows, but Cursor can render the narrow composer-tool-former-message approval surface inside the editor workbench zone.
lesson_extracted: true
---

## Symptoms

- The real-prompt replay suite passed 11 of 12 fixtures.
- `delete-file-reject-accept` remained visible but produced no click.
- The debug snapshot showed no eligible candidate because the injected
  `.composer-tool-former-message` was outside a virtual transcript row.

## Resolution

- Keep the mounted virtual-row roots.
- Also inspect the exact `.composer-tool-former-message` surface used by the
  preserved real Cursor prompt.
- Deduplicate overlapping roots and cap the combined scan at 100 roots.
- Never restore the old `document.body` nested subtree scan.

## Verification

After reinstalling injector hash `460391c03c13`, the 12-fixture real-prompt
replay passed 12/12 at the 0.5-second fallback cadence, including
`delete-file-reject-accept`.

## Lesson

Performance fixes must be replayed against preserved real misses. Tightening a
fallback root is safer only if known exceptional surfaces remain covered
through narrow, explicitly bounded selectors.
