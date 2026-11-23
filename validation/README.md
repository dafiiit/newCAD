# Validation

Analytic cases that run through the real engine (build123d → Gmsh → CalculiX for FEM, build123d → MJCF → MuJoCo
for motion) and compare one number with a closed-form reference. CI runs them on every push and puts the table in the job summary.

```sh
cd engine
uv run --extra dev python ../validation/report.py   # table
uv run --extra dev pytest ../validation             # pass/fail (Phase 3 and 4 gates)
```

| Case | Reference | Tolerance |
|---|---|---|
| Cantilever tip deflection, three mesh sizes | Timoshenko beam (bending + shear) | 2 % on the finest mesh, error must not grow as the mesh is refined |
| Cantilever first bending frequency | Euler–Bernoulli, β₁L = 1.8751 | 2 % |
| Plate with a hole in tension, peak stress | Peterson/Pilkey Kt for a finite-width plate | 5 % |
| Bar conducting heat | 1D conduction ΔT = P·L/(k·A) | 1 % |
| Four-bar crank-rocker, rocker angle over a crank turn | Loop-closure (circle intersection) position solution | 0.1° at every sample |
| Four-bar crank-rocker, rocker swing | Same, extreme positions | 0.2 % |
| Rotating link, bearing load at constant speed | Centripetal force m·ω²·r | 1 % |
| Bearing load → CalculiX | The static study's load equals MuJoCo's peak load; CalculiX's support reactions balance it | 1 % |

Needs CalculiX (`ccx`) on the PATH (`apt install calculix-ccx`, or `conda install -c conda-forge calculix`
on macOS; `NEWCAD_CCX` can point at the binary). The cases skip when it is missing. The motion cases need only MuJoCo,
which installs with the engine (the bearing hand-off case needs CalculiX too).
