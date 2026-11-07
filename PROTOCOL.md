# Eval protocol

Each eval poses a fixed question to one or more systems under test and grades their answers by a stated method. This repository stores the public half. That means the design and harness along with the grading method, and later the task set, once publishing it can no longer help a system under test. The private half shares the ID. It covers runs and raw transcripts, the scores, and anything that refers to private hosts or data.

## Layout and IDs

Put each eval in `evals/<ns>/e-NNNNNN-<slug>/`. The namespace is the tbhb-dev project the eval serves, or `_` for general work, and a new namespace needs a `README.md` like `evals/_/README.md`. Numbers are zero-padded to six digits, and each namespace counts from E-000001 on its own. The ID is `<ns>/E-NNNNNN`, such as `_/E-000001`, the same in frontmatter `id` and in prose.

Request a number from the coordinator before you create the directory, and never pick one yourself. One central counter per namespace serves both repositories, so the private half of `_/E-000001` sits at the same path in the private counterpart. Slugs are lowercase, dashed titles of at most about 60 characters. If the wording of the question changes later, don't rename the directory.

## The eval README

Its frontmatter has the fields `type: Eval`, `id`, `title`, and `state`. Its body has these sections:

- **Question:** what the eval decides, and for whom.
- **Systems under test:** every harness with its model, effort, and version.
- **Task set:** the tasks and how you chose them, and where you store the answer key.
- **Method:** how a run executes and how often each task repeats, and which conditions every system shares.
- **Grading:** the criteria and scale, and who grades blind and how.
- **Costs and bounds:** paid model turns, hosts, time, and the point at which to stop.
- **Status:** what ran and what didn't.

## Task sets and answer keys

A task set states its answer key, or the procedure that checks an answer, before any run starts. Freeze both at a commit and name that commit in every run. After the first run, change a task set by releasing a new version, which gets its own runs from scratch.

If a system under test could find an answer key, commit that key to the private half until the eval ends. Web research is the plain case. A public key on GitHub would let a harness look up the answers, so publish it here only after the last run.

## Lifecycle

The states are `designed`, `approved`, `running`, `blocked`, `partial`, `complete`, and `invalid`. An eval starts as `designed` and moves to `approved` once the coordinator accepts the design. Nobody starts a run before approval. COMPLETE means every planned run finished and a grader scored it, negative results included. PARTIAL means some runs never ran or failed. BLOCKED means nothing useful ran. INVALID means the eval didn't record a usable outcome. Update the README Status and `state` together.

## Grading and claims

Grade blind wherever a person or a model judges. Each grader sees an answer under a shuffled label. No grader sees the system's name, and the mapping from labels to systems remains in the private half until every score is final. Record each score with its rubric version and grader. Report sample counts and spread with every comparison, and keep measured, reported, inferred, and unproved claims apart.

## Before committing

The pre-commit hooks run the same gates as CI. Never bypass them, and never force-add ignored files. `bazelisk test //...` runs every gate at once, including the whole-tree checks that a hook skips because they need the full repository. Use Conventional Commits and a plain `git commit`, without `Signed-off-by` or `Co-authored-by`. Each file must stay at or below 20,000,000 bytes, which `size-check.sh` enforces on every commit. Write one line per paragraph.
