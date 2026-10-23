/*
 * SysML v2 system model – Metric Right-Angle Gear Box 2477N33, variant 2
 *
 * The same gearbox as GearBox_2477N33.sysml, written so that the BDS verification
 * (backend/app/projects/bds/) can read it. The original stays the full system model;
 * this one holds only the requirements BDS can check against the CAD geometry.
 *
 * What BDS reads (header of extract.py), and how this file follows it:
 *   * per requirement def exactly ONE comparison, ONE literal, ONE unit
 *       -> the limit lives in the definition, not in a usage that redefines it;
 *          a tolerance band (5.00 ± 0.02 mm) is two requirements, a lower and an upper bound
 *   * the subject comes from `satisfy <usage> by <part>`
 *       -> one satisfy per checked part, as a dotted path to the part usage
 *   * requirement ids are the definitions' names (no short names): the limit sync
 *     writes them as spreadsheet aliases, which allow letters, digits and _ only
 *
 * Measurable on the CAD side: bbox_size(axis), volume, mass, face_count,
 * cylinder_radius(kind, axis). Radii, not diameters -- cylinder_radius returns a radius.
 *
 * CAD objects: FreeCAD Names after the STEP import (STEP solid name in brackets); the
 * mapping lives in the BDS workspace data/bds/GearBox_2477N33_2/, not here. Cylinder
 * features read from the STEP file and confirmed through the bridge, 2026-10-23:
 *   gearBox        _2477N33_Metric_Right_Angle_Gear_Box (App::Part)  mass of all 15 bodies
 *   housing        Part__Feature010 (Cut-Extrude32)   bbox 40 x 25 x 40 mm
 *   inputShaft     Part__Feature008 (Cut-Extrude12)   boss, axis Z: r 2.5 AND r 2.373 (clip groove) -> ambiguous
 *   outputShaft    Part__Feature009 (Cut-Extrude13)   boss, axis X: r 2.5 only
 *   inputBearing   Part__Feature003   (not checked, see below)
 *   outputBearing  Part__Feature005   (not checked, see below)
 *   inputRetainer1/2   Part__Feature, Part__Feature001      boss, axis Z: r 8.0
 *   outputRetainer1/2  Part__Feature002, Part__Feature007   boss, axis X: r 8.0
 *   retaining rings    Part__Feature004, Part__Feature006
 *   screw plugs        Part__Feature011 .. Part__Feature014
 *
 * Expect two kinds of gap, both correct behaviour (a gap is never a pass):
 *   * inputShaft radius: two boss cylinders on the Z axis, cylinder_radius cannot tell
 *     the journal from the groove
 *   * mass: STEP carries no material -- assign Aluminium (housing) and Steel (the rest)
 *     in FreeCAD first; the assembly's mass is the sum of its bodies
 * The envelope limits equal the nominal size (40 / 25 / 40 mm): a measurement of
 * 40.0000001 mm is "violated". Give those mapping entries `tolerance: "0.01 mm"`.
 *
 * Left out of this variant, and why:
 *   REQ-KIN-1/2/3  angle, ratio, mesh clearance -- no BDS measurement; angle and ratio
 *                  are unit-less Reals
 *   REQ-IF-1       shaft protrusion -- no measurement for "length outside the housing"
 *   REQ-IF-2       hole count and pattern offset -- face_count counts faces, not holes
 *   REQ-MECH-1     bearing bore and OD, housing bore -- ambiguous for cylinder_radius
 *                  (bearing: 2 hole + 2 boss features per axis; housing: 8 per axis);
 *                  the shaft journal is checked through the shaft radius below
 *   REQ-MECH-2     torque -- an operating value, not geometry
 */
package GearBox_2477N33_2 {
    private import ScalarValues::*;
    private import ISQ::*;
    private import SI::*;

    /* ---------- parts ---------- */

    part def Housing {
        doc /* Prismatic block housing; length X, width Y, height Z (STEP global frame). */
        attribute length : LengthValue;
        attribute width  : LengthValue;
        attribute height : LengthValue;
    }

    part def ShaftWithBevelGear {
        doc /* Steel shaft with integral bevel pinion, Ø5 journal. */
        attribute shaftRadius : LengthValue;
    }

    part def BearingRetainerSegment {
        doc /* Half-ring in the Ø16 counterbore, axially locks the bearing. */
        attribute outerRadius : LengthValue;
    }

    part def RadialBearing;
    part def ShaftRetainingRing;
    part def ScrewPlug;

    part def RightAngleGearBox {
        doc /* 1:1 right-angle bevel gearbox; +Z shaft = input, +X shaft = output. */
        attribute mass : MassValue;
    }

    /* ---------- requirements: one bound each ---------- */

    requirement def MaxHousingLength {
        doc /* REQ-ENV: the housing shall not exceed 40 mm in length (X). */
        subject housing : Housing;
        attribute maxLength : LengthValue = 40 [mm];
        require constraint { housing.length <= maxLength }
    }

    requirement def MaxHousingWidth {
        doc /* REQ-ENV: the housing shall not exceed 25 mm in width (Y). */
        subject housing : Housing;
        attribute maxWidth : LengthValue = 25 [mm];
        require constraint { housing.width <= maxWidth }
    }

    requirement def MaxHousingHeight {
        doc /* REQ-ENV: the housing shall not exceed 40 mm in height (Z). */
        subject housing : Housing;
        attribute maxHeight : LengthValue = 40 [mm];
        require constraint { housing.height <= maxHeight }
    }

    requirement def MinShaftRadius {
        doc /* REQ-IF-1 / REQ-MECH-1, lower bound: shaft Ø5.00 -0.02 mm, i.e. radius >= 2.49 mm. */
        subject shaft : ShaftWithBevelGear;
        attribute minRadius : LengthValue = 2.49 [mm];
        require constraint { shaft.shaftRadius >= minRadius }
    }

    requirement def MaxShaftRadius {
        doc /* REQ-IF-1 / REQ-MECH-1, upper bound: shaft Ø5.00 +0.02 mm, i.e. radius <= 2.51 mm. */
        subject shaft : ShaftWithBevelGear;
        attribute maxRadius : LengthValue = 2.51 [mm];
        require constraint { shaft.shaftRadius <= maxRadius }
    }

    requirement def MaxRetainerOuterRadius {
        doc /* Derived from the design check chkRetainerInCounterbore: the retainer segment
               shall fit the Ø16 counterbore, i.e. outer radius <= 8 mm. */
        subject retainer : BearingRetainerSegment;
        attribute maxRadius : LengthValue = 8 [mm];
        require constraint { retainer.outerRadius <= maxRadius }
    }

    requirement def MaxTotalMass {
        doc /* REQ-MASS: the assembled gearbox shall not exceed 130 g
               (ASSUMPTION: budget incl. ~10 % margin; expected ≈ 117.8 g). */
        subject gb : RightAngleGearBox;
        attribute maxMass : MassValue = 130 [g];
        require constraint { gb.mass <= maxMass }
    }

    /* ---------- the as-modelled configuration ---------- */

    part gearBox : RightAngleGearBox {
        part housing         : Housing;
        part inputShaft      : ShaftWithBevelGear;
        part outputShaft     : ShaftWithBevelGear;
        part inputBearing    : RadialBearing;
        part outputBearing   : RadialBearing;
        part inputRetainingRing  : ShaftRetainingRing;
        part outputRetainingRing : ShaftRetainingRing;
        part inputRetainer1  : BearingRetainerSegment;
        part inputRetainer2  : BearingRetainerSegment;
        part outputRetainer1 : BearingRetainerSegment;
        part outputRetainer2 : BearingRetainerSegment;
        part plugRearUpper   : ScrewPlug;
        part plugInnerUpper  : ScrewPlug;
        part plugInnerLower  : ScrewPlug;
        part plugBottom      : ScrewPlug;
    }

    requirement housingLengthCheck   : MaxHousingLength;
    requirement housingWidthCheck    : MaxHousingWidth;
    requirement housingHeightCheck   : MaxHousingHeight;
    requirement shaftMinRadiusCheck  : MinShaftRadius;
    requirement shaftMaxRadiusCheck  : MaxShaftRadius;
    requirement retainerRadiusCheck  : MaxRetainerOuterRadius;
    requirement totalMassCheck       : MaxTotalMass;

    // One satisfy per checked part; a requirement satisfied by several parts is
    // checked once per part (MinShaftRadius@inputShaft, ...).
    satisfy housingLengthCheck  by gearBox.housing;
    satisfy housingWidthCheck   by gearBox.housing;
    satisfy housingHeightCheck  by gearBox.housing;
    satisfy shaftMinRadiusCheck by gearBox.inputShaft;
    satisfy shaftMinRadiusCheck by gearBox.outputShaft;
    satisfy shaftMaxRadiusCheck by gearBox.inputShaft;
    satisfy shaftMaxRadiusCheck by gearBox.outputShaft;
    satisfy retainerRadiusCheck by gearBox.inputRetainer1;
    satisfy retainerRadiusCheck by gearBox.inputRetainer2;
    satisfy retainerRadiusCheck by gearBox.outputRetainer1;
    satisfy retainerRadiusCheck by gearBox.outputRetainer2;
    satisfy totalMassCheck      by gearBox;
}
