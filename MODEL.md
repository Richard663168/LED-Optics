# Emitting-dipole solver

`dipole.py` supplies an isotropic planar angular-spectrum / Green-function solver. It is separate from `engine.py` (external-illumination tmm), and runs in a browser worker so the editor remains responsive.

The lossless source host has index `Re(n_QD)` and the other film indices retain `n+ik`. This transparent-host approximation is explicit: emitter absorption, local-field corrections, intrinsic nonradiative recombination and photon recycling are excluded. It avoids presenting the divergent local absorption of a macroscopic absorbing point-source host as a physical efficiency.

`q = k_parallel/k0`; `w_j = sqrt(n_j^2-q^2)` on the passive branch. Tangential-E admittances are `Y_s=w`, `Y_p=n^2/w`; in this convention p reflection has the opposite sign to tmm's polarization-vector convention. Stable recursive r,t avoid exponentially growing transfer matrices.

For a source at z in thickness d, `a=r_left exp(2ik0 w z)`, `b=r_right exp(2ik0 w(d-z))`, `D=1-ab`. Horizontal cavity factor is `(1+a)(1+b)/D`; vertical p is `(1-a)(1-b)/D`. The normalized total-power integrands are:

- horizontal s: `(3/4) Re[q/(n_e w) F_h]`
- horizontal p: `(3/4) Re[q w/n_e^3 F_h]`
- vertical p: `(3/2) Re[q^3/(n_e^3 w) F_v]`

For downward flux, the field factor is `t_left exp(ik0 w z) (1+b)/D` (horizontal) or `(1-b)` (vertical). Multiplying squared magnitudes by the corresponding output admittance gives far-field powers, including tunneling from source-evanescent waves into a higher-index output. Upward expressions exchange left/right and z/(d-z).

All powers are relative to the same dipole in the infinite transparent source host at that wavelength. Horizontal and vertical dipole fractions and depth weights are combined as powers. Spectral weights mean relative source powers in this normalization. Ratios use the averaged numerator and denominator, not mean efficiencies. The reported total factor is an electromagnetic rate enhancement, not a full measured lifetime or EQE.

The substrate is an incoherent finite glass slab terminated in the incident/extraction medium. Glass loss is included as propagation attenuation based on complex kz; coherent film coupling uses a real glass halfspace. This assumes weak substrate absorption (appropriate to transparent glass). An incoherent return factor `T_glass-air * attenuation / (1-R_glass-air R_stack attenuation^2)` accounts for repeated specular passes. No photon recycling or scattering rescues totally internally reflected light. This calculation is not intended for strongly absorbing substrates.

Quadrature splits light lines and uses a sin-squared endpoint transform. It compares orders 64/128 and, where necessary, 256; uniform depth uses 8/16/32 points inside the specified interface inset. The evanescent upper cutoff puts the interface exponential at at least exp(-24), with q_max at least 12. Agreement between grids is not proof that an arbitrarily narrow bound-mode pole has been resolved. The app flags lossless stacks and failed convergence/power balance; these must not be treated as publication-ready efficiencies.

References: Lukosz & Kunz, JOSA 67, 1607 (1977), DOI 10.1364/JOSA.67.001607; Neyts, Applied Optics 39, 3968 (2000), DOI 10.1364/AO.39.003968. Implementation is independent and does not copy a third-party solver.

Validation: `python tests/test_physics.py` checks homogeneous-medium orientation limits, half-space energy balance, reflection/transmission agreement with tmm for an absorbing metal film, the near-perfect-mirror orientation limits, positive lossy-cavity channels, spectral power weighting, uniform depth integration and glass attenuation. Browser QA covers loading/running the worker and displaying the resulting metrics, source-depth control, and passive calculation.
