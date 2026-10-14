// The two-part reference assembly, on the SysML side.
//
// The CAD side of this already exists as cad/gearbox.py and
// fixtures/step/gearbox.step. This file is its counterpart, and it exists for a
// reason the single-part model cannot serve: with one part and two attributes,
// part-anchored mapping is untested by anything except its own design, and a
// mapping proposer that gets 2 of 2 right has demonstrated nothing.
//
// Three things it adds over motor_housing.sysml:
//
//   * TWO parts under one assembly, so a mapping has to pick the right one
//   * an INTERFACE dimension -- the bore both parts must agree on, which is the
//     "interface control" case from the use-case slides
//   * an assembly-level MASS BUDGET, checked against the sum of the components
//
// Kept deliberately within what the extractor can read today: one comparison per
// requirement, one literal, one unit (see the header of extract.py). The
// equality between the two bore radii, which is the constraint an engineer would
// actually write, is exactly the compound case that needs the constraint
// expression resolved -- so it is written as two independent bounds here, and
// the shortcoming is the point rather than a mistake.
//
// Same two syntax rules that cost time to rediscover (release 0.60.1):
//   * visibility on imports is mandatory: `private import`, not `import`
//   * `satisfy` needs a requirement USAGE, not a definition
package Gearbox {
    private import ScalarValues::*;
    private import ISQ::*;
    private import SI::*;

    part def Housing {
        attribute length     : LengthValue;
        attribute width      : LengthValue;
        attribute height     : LengthValue;
        attribute boreRadius : LengthValue;
        attribute mass       : MassValue;
    }

    part def Cover {
        attribute length     : LengthValue;
        attribute width      : LengthValue;
        attribute thickness  : LengthValue;
        attribute boreRadius : LengthValue;
        attribute mass       : MassValue;
    }

    part def GearboxAssembly {
        attribute mass : MassValue;
    }

    requirement def MaxHousingLength {
        doc /* The gearbox housing must not exceed 95 mm in length. */
        subject housing : Housing;
        attribute maxLength : LengthValue = 95 [mm];
        require constraint { housing.length <= maxLength }
    }

    requirement def MaxCoverThickness {
        doc /* The cover must not exceed 8 mm in thickness. */
        subject cover : Cover;
        attribute maxThickness : LengthValue = 8 [mm];
        require constraint { cover.thickness <= maxThickness }
    }

    requirement def MinBoreRadius {
        doc /* The bore must be at least 8 mm in radius -- the shaft interface.
               Housing and cover have to agree on this; today each is checked
               against the agreed figure separately. */
        subject housing : Housing;
        attribute minRadius : LengthValue = 8 [mm];
        require constraint { housing.boreRadius >= minRadius }
    }

    requirement def MaxAssemblyMass {
        doc /* The assembled gearbox must not exceed 1.5 kg. This is the budget
               the components are allocated out of. */
        subject assembly : GearboxAssembly;
        attribute maxMass : MassValue = 1.5 [kg];
        require constraint { assembly.mass <= maxMass }
    }

    part gearbox : GearboxAssembly {
        part housing : Housing;
        part cover   : Cover;
    }

    requirement housingLengthCheck  : MaxHousingLength;
    requirement coverThicknessCheck : MaxCoverThickness;
    requirement boreRadiusCheck     : MinBoreRadius;
    requirement assemblyMassCheck   : MaxAssemblyMass;

    // The links the extractor resolves to learn which part each requirement is
    // about. Without these, every requirement's subject falls back to the
    // definition's own subject parameter -- see extract.resolve_satisfies.
    satisfy housingLengthCheck  by gearbox.housing;
    satisfy coverThicknessCheck by gearbox.cover;
    satisfy boreRadiusCheck     by gearbox.housing;
    satisfy assemblyMassCheck   by gearbox;
}
