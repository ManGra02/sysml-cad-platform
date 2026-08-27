// Reference model of the PoC.
//
// This file must stay in step with notebooks/01_publish_motor_housing.ipynb --
// the notebook is what actually reaches the server, and a divergence here is
// invisible until the extracted requirement ids stop matching mapping.yaml.
//
// Two syntax rules that cost time to rediscover (release 0.60.1):
//   * visibility on imports is mandatory: `private import`, not `import`
//   * `satisfy` needs a requirement USAGE, not a definition -- hence the
//     maxLengthCheck / maxMassCheck usages below
package MotorHousing {
    private import ScalarValues::*;
    private import ISQ::*;
    private import SI::*;

    part def Housing {
        attribute length : LengthValue;
        attribute mass   : MassValue;
    }

    requirement def MaxLength {
        doc /* The motor housing must not exceed 120 mm in length. */
        subject housing : Housing;
        attribute maxLength : LengthValue = 120 [mm];
        require constraint { housing.length <= maxLength }
    }

    requirement def MaxMass {
        doc /* The mass of the motor housing must not exceed 0.9 kg. */
        subject housing : Housing;
        attribute maxMass : MassValue = 0.9 [kg];
        require constraint { housing.mass <= maxMass }
    }

    part motorHousing : Housing;

    requirement maxLengthCheck : MaxLength;
    requirement maxMassCheck   : MaxMass;

    // These two links are what the extractor resolves to learn that these
    // requirements are about motorHousing. See extract.resolve_satisfies.
    satisfy maxLengthCheck by motorHousing;
    satisfy maxMassCheck   by motorHousing;
}
