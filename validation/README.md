# Validation

Analytic cases that run through the real engine (build123d → Gmsh → CalculiX) and compare one number
with a closed-form reference. CI runs them on every push and puts the table in the job summary.

```sh
cd engine
uv run --extra dev python ../validation/report.py   # table
uv run --extra dev pytest ../validation             # pass/fail (Phase 3 gate)
```

| Case | Reference | Tolerance |
|---|---|---|
| Cantilever tip deflection, three mesh sizes | Timoshenko beam (bending + shear) | 2 % on the finest mesh, error must not grow as the mesh is refined |
| Cantilever first bending frequency | Euler–Bernoulli, β₁L = 1.8751 | 2 % |
| Plate with a hole in tension, peak stress | Peterson/Pilkey Kt for a finite-width plate | 5 % |
| Bar conducting heat | 1D conduction ΔT = P·L/(k·A) | 1 % |

Needs CalculiX (`ccx`) on the PATH (`apt install calculix-ccx`, or `conda install -c conda-forge calculix`
on macOS; `NEWCAD_CCX` can point at the binary). The cases skip when it is missing.
