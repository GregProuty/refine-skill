# Round {{N}} response ({{"spec revised to rev X" | "no subject change"}})

Reviewed `round-{{N}}.json` against the subject at `{{head reviewed}}`. {{one line: how many accepted / rejected / deferred; which prior IDs Codex confirmed.}}

{{for each new or reopened finding, one section:}}
## {{ID}} [{{P0..P3}}]: {{title}}

{{Verdict first: "Confirmed" / "Rejected" / "Deferred". Then what was verified against the subject or code (file:line), what changed and where (section or file), or for a rejection the evidence Codex missed. For a reopened ID, address the new evidence explicitly. No thanks, no "you're right".}}

## Also changed

{{anything changed that no finding asked for, or "- (nothing)"}}

## Files changed

{{files}}

<!-- end -->
