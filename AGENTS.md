# Agent instructions

This is tbhb-dev/evals, the public repository of evaluations for tbhb-dev work. It contains the harnesses, the task sets, and the generic methods, and every file is new, clean work. A private counterpart stores the runs and transcripts, along with anything that refers to private hosts, repositories, or data. Never copy content from it into this repository.

## Standing rules

- Everything here is public. Never write a private repository's name, a private host name, tailnet details, an internal URL, or anything from private work. Refer to a machine by its role, such as `peer-mac` or `linux-peer`.
- Never write a public IP address in a commit, a pull request, or a document. The `public-ipv4` gitleaks rule enforces this.
- Never open credential files, print secrets, or commit secret values. Secrets live in 1Password only.
- Before choosing a model for a subagent or peer run, read models/README.md in tbhb-dev/wiki (<https://github.com/tbhb-dev/wiki/blob/main/models/README.md>).

## Writing an eval

[PROTOCOL.md](PROTOCOL.md) sets the layout and the IDs, and the lifecycle too. Put each eval in `evals/<ns>/e-NNNNNN-<slug>/`, with its design in `README.md`. Its ID is `<ns>/E-NNNNNN`, such as `_/E-000001`. The coordinator assigns the number, so request one and never pick it yourself.

- Don't commit an answer key here while the eval runs, because a harness under test can search GitHub.
- Keep measured, reported, inferred, and unproved claims distinct.
- Evals inform design, and the repository a decision concerns records it. Don't edit another repository's documentation from here.
- Write each Markdown paragraph on one line.

## Commits and pull requests

- Branch first, as `eval/<ns>/e-NNNNNN-<slug>`. Every change lands through a pull request.
- Use Conventional Commits and a plain `git commit`, without `Signed-off-by` or `Co-authored-by`, and fill every section of `.github/PULL_REQUEST_TEMPLATE.md`.

## Checks

Run `mise install` and `bazelisk run //:bazel_env`, which builds the `.bazel_env/bin` shims the git hooks call, then `tbhbdev alpha install` once per machine. It installs the user-level harness hooks, and each session start then installs this clone's git hooks. Every gate is a Bazel test from tbhb-dev/rules, which `bazelisk test //...` runs, and `bazelisk run //:format` rewrites files into their canonical format. The pre-commit hooks run the same gates. To build against a local rules clone, put `common --override_module=tbhb_rules=<path to a rules clone>` in `.bazelrc.user`.
