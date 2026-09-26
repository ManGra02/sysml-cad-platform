// Box1 -- the first model checked against a CAD file this repository did not
// generate itself: projects/box1/Box1.step, a plain cuboid exported by an
// OpenCASCADE-based tool.
//
// Stated design: length 300 mm, width 400 mm, height 500 mm. The requirements
// below are that envelope, one upper bound per dimension -- the same shape as
// MaxLength in motor_housing.sysml, and within what the extractor reads today
// (one comparison, one literal, one unit per requirement).
//
// Which CAD axis carries which dimension is NOT stated here. SysML says
// "length"; the mapping (projects/box1/mapping.yaml) says which bounding-box
// axis stands for it. That split is deliberate: see the note there.
//
// This file must stay in step with notebooks/03_publish_box1.ipynb -- the
// notebook is what reaches the server.
package Box1 {
    private import ScalarValues::*;
    private import ISQ::*;
    private import SI::*;

    part def Box {
        attribute length : LengthValue;
        attribute width  : LengthValue;
        attribute height : LengthValue;
    }

    requirement def MaxLength {
        doc /* The box must not exceed 300 mm in length. */
        subject box : Box;
        attribute maxLength : LengthValue = 300 [mm];
        require constraint { box.length <= maxLength }
    }

    requirement def MaxWidth {
        doc /* The box must not exceed 400 mm in width. */
        subject box : Box;
        attribute maxWidth : LengthValue = 400 [mm];
        require constraint { box.width <= maxWidth }
    }

    requirement def MaxHeight {
        doc /* The box must not exceed 500 mm in height. */
        subject box : Box;
        attribute maxHeight : LengthValue = 500 [mm];
        require constraint { box.height <= maxHeight }
    }

    part box1 : Box;

    requirement lengthCheck : MaxLength;
    requirement widthCheck  : MaxWidth;
    requirement heightCheck : MaxHeight;

    satisfy lengthCheck by box1;
    satisfy widthCheck  by box1;
    satisfy heightCheck by box1;
}
