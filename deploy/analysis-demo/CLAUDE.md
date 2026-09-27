# kazakhstan-law: analysis workspace

Each directory here is a git clone of one repository of the kazakhstan-law corpus
(https://github.com/kazakhstan-law): the legal acts of Kazakhstan, one commit per version.
The working tree of a repository at any commit is the law in force on that commit's date.

## Layout

- `codes/`, `government/`, `ministerial/`, and one `local-<region>/` per region (22).
- Inside each: tier directories (`00-constitution`, `02-codes`, `03-laws`, `06-government`,
  `07-ministerial`, `08-local-decisions`, …), then the approving agency
  (`<agency-code>-<slug>/`) where the tier has one, then `<YYYY>/<MMDD>-<title-slug>-<act-code>/`.
- An act directory holds `rus.md`, `kaz.md` and `meta.yaml` (code, title, requisite, form,
  approved_on, approved_by agency codes, caused_by: the act that caused this version).
- Large documents are split: `rus.md` becomes an index and the parts sit in `rus/`.
- Articles carry anchors: `<a id="st62"></a>`.

## History

- Commit date = the date the version took effect. Author = the agency that approved the act
  that caused the change (name and agency code in the e-mail).
- Commit trailers: `Cause-Act-Code`, `Cause-Act-Requisite`, `Acts-Changed`.
  `git log --grep='^Cause-Act-Code: 226744'` finds everything one act amended.
- A repeal is a deletion: the act's files are removed in the commit of the repealing act.

## How to work

- Answer in Russian, plainly. Give the numbers, say in one line how you got them, and name
  the limits of the method.
- Use git, rg and short Python scripts (python3, standard library). Put scripts in
  `/tmp/kzlaw-analysis/`. Never modify, checkout, reset or fetch in the repositories.
- Link to acts as `https://github.com/kazakhstan-law/<repo>/blob/<commit>/<path>`.
