# Project-local RTK usage

RTK is installed as a verified workspace-local helper. It filters command output before
that output reaches the agent context; it does not change project runtime behavior.

The installed binary is RTK `0.45.0` from the official GitHub Release. The downloaded
Windows archive matched the published SHA-256 value
`34cea9009a8099acdaf85147b971d95f65efabfa63fb3aea7d3e2b73e6f517c3`.

The PowerShell wrapper accepts only fixed, argument-free profiles:

```text
powershell -NoProfile -File scripts\invoke-rtk.ps1 -Profile version
powershell -NoProfile -File scripts\invoke-rtk.ps1 -Profile pytest
powershell -NoProfile -File scripts\invoke-rtk.ps1 -Profile ruff
powershell -NoProfile -File scripts\invoke-rtk.ps1 -Profile mypy
powershell -NoProfile -File scripts\invoke-rtk.ps1 -Profile gain
```

The wrapper applies these boundaries:

- optional RTK telemetry is explicitly disabled;
- callers cannot append arbitrary commands, flags, paths, URLs or values;
- each standalone profile uses a unique tracking database that is deleted in `finally`;
- the quality smoke shares one ephemeral tracking database only long enough to report
  savings, then deletes it;
- raw failure-output tee files are disabled;
- the wrapper verifies the extracted executable SHA-256 before every invocation;
- no global Codex or Claude hook installation is attempted;
- the project virtual environment is available to child commands;
- the caller's working directory and modified process environment are restored.

There is deliberately no generic `.cmd <arbitrary arguments>` entry point and no RTK
profile for credentials, cookies, runtime-session material, G0 personal information,
URLs, environment dumps, Docker mutation, or source page bodies.

Run `scripts\run-rtk-quality-smoke.cmd` for the full compact pytest, Ruff and strict
mypy check. Its status-only log and structured report are written under `var\reports`;
test failure bodies are not persisted by that log.

RTK's savings figure estimates shell-output reduction from character counts. It is not
a billing or total-conversation token guarantee. On Windows, RTK 0.45.0 can display
`No tests collected` when successful pytest output is already double-quiet; the quality
smoke therefore validates RTK's exit code and obtains the authoritative test count from
a separate native collection check.
