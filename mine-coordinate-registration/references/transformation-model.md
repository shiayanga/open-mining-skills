# Transformation Model Notes

## Convention

All transformations use:

```text
dst = scale * R * src + translation
```

`src` and `dst` are 3D column vectors in the source and target coordinate systems. The rotation matrix `R` is a proper rotation (`det(R) = +1`); reflections are rejected by the SVD correction.

## 3D seven-parameter similarity

The model has seven parameters:

| Parameter | Meaning |
|---|---|
| `tx`, `ty`, `tz` | Translation |
| `rx`, `ry`, `rz` | Rotation, reported as ZYX Euler angles in degrees |
| `scale` | Uniform scale factor |

### Estimation (Umeyama / SVD)

1. Centre both point sets by their means.
2. Compute the cross-covariance `C = (dst_c.T @ src_c) / n`.
3. SVD: `C = U D Vt`.
4. Correct reflection: if `det(U) * det(Vt) < 0`, set `S = diag(1, 1, -1)`.
5. Rotation: `R = U S Vt`.
6. Scale: `trace(diag(D) S) / variance(src_c)`.
7. Translation: `mu_dst - scale * R @ mu_src`.

### Euler angle extraction

`R = Rz(rz) @ Ry(ry) @ Rx(rx)`, with:

```text
ry = atan2(-R[2,0], hypot(R[0,0], R[1,0]))
rx = atan2(R[2,1], R[2,2])
rz = atan2(R[1,0], R[0,0])
```

Angles are reported in degrees. Compare angles modulo 360° when validating.

## 2D four-parameter similarity

The horizontal model is:

```text
x' = a*x - b*y + tx
y' = b*x + a*y + ty
```

- `scale = hypot(a, b)`
- `rotation = atan2(b, a)`
- Z receives a constant mean offset: `tz = mean(dst_z - src_z)`.
- Residuals are horizontal distances; Z is not fitted beyond the offset.

## Residuals

For each control point:

- 3D mode: `residual = ||transformed - target||`
- 2D mode: `residual = hypot(dx, dy)`

Reported statistics:

- `rmse = sqrt(mean(residual²))` over used points
- `mean_residual`, `max_residual`
- per-axis RMSE (`x`, `y`, `z`)
- per-point `dx`, `dy`, `dz`, `transformed` coordinates

## Outlier rejection

`--reject-above` sets an **absolute residual threshold** in the active units:

1. Fit on all kept points.
2. Compute residuals for kept points.
3. Remove the worst point above the threshold.
4. Refit and repeat until no point exceeds the threshold or the minimum count is reached.

Rejected points keep their removal residual and reason in the report.

## Minimum points and degeneracy

- 3D: at least 3 points, and the centred source points must have rank ≥ 2. Collinear points leave rotation about the line undetermined.
- 2D: at least 2 distinct points.
- Fewer than 4 (3D) or 3 (2D) used points produce a warning that RMSE is not a reliable accuracy estimate.

## Limitations

- CRS definitions and EPSG-based transforms are not implemented in v0.1; `pyproj` support is planned.
- Parameters are valid only for this control point set and coordinate pair.
- The rotation centre is implicit: translation absorbs the effect of rotating about the origin.
- Scale is unitless; unit changes must be resolved before fitting.
- Horizontal and vertical datums are not separated in v0.1.
- Confidence intervals for parameters are not computed.
