package MotorHousing {
    import ISQ::*;
    import SI::*;

    part def Housing {
        attribute length : LengthValue;
        attribute mass   : MassValue;
    }

    requirement def <'REQ001'> MaxLength {
        doc /* Die maximale Laenge des Motorgehaeuses darf 120 mm nicht ueberschreiten. */
        subject housing : Housing;
        attribute maxLength : LengthValue = 120 [mm];
        require constraint { housing.length <= maxLength }
    }

    requirement def <'REQ002'> MaxMass {
        doc /* Die Masse des Motorgehaeuses darf 0,9 kg nicht ueberschreiten. */
        subject housing : Housing;
        attribute maxMass : MassValue = 0.9 [kg];
        require constraint { housing.mass <= maxMass }
    }

    part motorHousing : Housing;

    satisfy MaxLength by motorHousing;
    satisfy MaxMass   by motorHousing;
}
