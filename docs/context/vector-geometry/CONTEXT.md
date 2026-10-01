# SVG geometry and print coordinates

This context owns native SVG topology, its handoff to the print grid, and the
geometry shared by ordinary generation, edits, auxiliary parts and tiling.

- [Root cause](ROOT_CAUSE.md): the reported failure and why the two coordinate
  transitions must not run topology operations on scaled floating views.
- [Coordinate contract](COORDINATE_CONTRACT.md): units, ownership, caches,
  consumers, quantization and runtime identity.
- [Validation report](TEST_REPORT.md): executed checks and remaining limits.

The material solver, printer profiles, 3MF writer and resource scheduling remain
owned by their existing modules. This change adds no converter request parameter.
