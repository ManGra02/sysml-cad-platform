// Drehungen reisen als Quaternion (x, y, z, w) -- nur so ist die Rundreise
// verlustfrei. Menschen editieren aber Achse + Winkel in Grad. Die Umrechnung
// passiert ausschliesslich hier, und nur, wenn der Nutzer die Drehung auch
// wirklich angefasst hat: sonst erzeugte das Runden eine Scheinaenderung.

export type AxisAngle = { axis: [number, number, number]; angle: number }

const EPS = 1e-12

/** FreeCADs Konvention: Quaternion als [x, y, z, w]. */
export function quatToAxisAngle(q: number[]): AxisAngle {
  let [x, y, z, w] = q
  const norm = Math.hypot(x, y, z, w) || 1
  x /= norm
  y /= norm
  z /= norm
  w /= norm
  if (w < 0) {
    // gleiche Drehung, Winkel dann in [0, 180]
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
    throw new Error("Drehachse darf nicht (0, 0, 0) sein")
  }
  const half = (angleDeg * Math.PI) / 360
  const s = Math.sin(half) / length
  return [axis[0] * s, axis[1] * s, axis[2] * s, Math.cos(half)]
}
