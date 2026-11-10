# Bound review launch

Use this reference for a supplied `ReviewLaunchRequest/v1`, launch diagnostics,
or read-only inspection. The request file is data: its hash and installed binding
fix one MergeReviewer, request ID, workspace, Repo, branches and native runtime.
Model and effort remain in the independent routing record.

## New and resumed requests

Execute the supplied runner command, changing only `--action`:

```text
python -X utf8 -B <runner> --review-request <request.json> --expected-request-sha256 <sha256> --action start
```

Actions are `preflight`, `start`, `status`, `view`, `check`, `finish` and `cancel`.
`start` validates the request, installed payload and runner identities. For a new
job it runs native read-only preflight before preparing scratch directories or
capturing evidence. Existing jobs enter native start's saved-input validation;
they do not repeat live preflight or capture. New drafts use supported compact
format; recovery preserves the native saved draft. `status` returns its summary.

Keep the request file unchanged. A hash mismatch or changed installed binding
requires the host to recreate the bound request. A diagnostic about the executed
path does not prove the user's original input was wrong; compare it with the
bound request. Preflight failures create no native job. Do not repair a failed
path by changing the immutable JSON or silently selecting a different Repo.

`view` accepts only native paging options after `--`, for example:

```text
python -X utf8 -B <runner> --review-request <request.json> --expected-request-sha256 <sha256> --action view -- --artifact <hash> --pointer /operations/0/result/lines --offset 0 --page-size 100
```

Use returned continuation offsets and preserve artifact scope. Identity arguments
cannot be added after `--`. `status`, `view` and `preflight` do not prepare a
scratch runtime; native read-only view also leaves paging metrics unchanged.
Native `step` continues through its documented runner command and saved operation
file because it mutates the evidence ledger. Keep its request ID/runtime fixed.

## Legacy command inspection

The original `run.py [--runtime-root PATH] -- COMMAND ...` remains available and
prepares writable scratch directories. For authenticated installed helpers with
the inspection capability, `run.py --read-only -- COMMAND ...` skips this setup.
It accepts Merge `capabilities`, `status --summary`, `view --read-only`, routing
`status`, and syntax `capabilities`; other commands retain normal runtime checks.
Use the ordinary command when an older installed Reviewer lacks the capability.

The runner's scratch directory is separate from native ownership:
`<native-runtime>-workflow-kit` for native review commands, and
`<install-root>/.gitlab-workspace/runtime` for other helpers. Never pass the native
runtime as the runner's scratch override. A write-permission failure during a
mutating command remains a real failure; read-only mode does not authorize writes.

The managed `runner-capabilities.json` declares this protocol. Its file hash and
`review_launch.py` are authenticated by the installation manifest; copied bindings
also pin the launcher hash. Older bindings continue with the legacy argv protocol.
