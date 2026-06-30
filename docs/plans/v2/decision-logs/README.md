# V2 Decision Logs

Each v2 implementation phase writes one short decision log before the next
phase starts.

Purpose:

- preserve architecture decisions that would otherwise live only in agent context;
- give the next phase a short handoff file to read first;
- keep the v2 build lane coherent across a long refactor.

Naming convention:

- `phase-1.md`
- `phase-2.md`
- `phase-3.md`
- `phase-4.md`
- `phase-5.md`
- `phase-6.md`

Each file should answer:

1. What did this phase decide?
2. Why did we choose it?
3. What changed because of it?
4. What should the next phase read first?

Use `phase-template.md` for the format.
