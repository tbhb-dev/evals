# Evals

This public repository contains evaluations for tbhb-dev work. For each one it stores the harness and the task set, along with the method that grades the answers. Everything here is new, clean work. A private counterpart stores the runs and their transcripts.

## Layout

Each tbhb-dev project gets a namespace under `evals/`, and `evals/_/` takes general work. Each eval is a directory `evals/<ns>/e-NNNNNN-<slug>/` with the ID `<ns>/E-NNNNNN`, such as `_/E-000001`, and its design in `README.md`. [PROTOCOL.md](PROTOCOL.md) has the details.

## Workflow

Every eval lands through a pull request. See [AGENTS.md](AGENTS.md) for the setup and the rules.

## Checks

Bazel runs every gate from tbhb-dev/rules: `bazelisk test //...`.
