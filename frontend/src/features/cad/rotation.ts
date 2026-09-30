import { TranslatableError } from "@/i18n"

// Rotations travel as quaternions (x, y, z, w) -- only that way is the round
// trip lossless. Humans, however, edit axis + angle in degrees. The conversion
// happens exclusively here, and only if the user actually touched the
// rotation: otherwise rounding would produce a spurious change.

export type AxisAngle = { axis: [number, number, number]; angle: number }

const EPS = 1e-12

/** FreeCAD's convention: quaternion as [x, y, z, w]. */
export function quatToAxisAngle(q: number[]): AxisAngle {
  let [x, y, z, w] = q
  const norm = Math.hypot(x, y, z, w) || 1
  x /= norm
  y /= norm
  z /= norm
  w /= norm
  if (w < 0) {
    // same rotation, angle then in [0, 180]
    x = -x
    y = -y
    z = -z
    w = -w
  }
  const s = Math.sqrt(Math.max(0, 1 - w * w))
  const angle = (2 * Math.acos(Math.min(1, w)) * 180) / Math.PI
  if (s < EPS) return { axis: [0, 0, 1], angle: 0 }
  return { axis: [x / s, y / s, z / s], angle }
}

export function axisAngleToQuat(axis: [number, number, number], angleDeg: number): number[] {
  const length = Math.hypot(...axis)
  if (length < EPS) {
    if (Math.abs(angleDeg) < EPS) return [0, 0, 0, 1]
    throw new TranslatableError("fields.zeroAxis")
  }
  const half = (angleDeg * Math.PI) / 360
  const s = Math.sin(half) / length
  return [axis[0] * s, axis[1] * s, axis[2] * s, Math.cos(half)]
}
