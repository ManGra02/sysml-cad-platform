// Box2 -- the second Chili3D export: projects/box2/Box2.step, a plain cuboid.
// It exists to confirm, with three different numbers, how Chili3D orients a
// box -- the axis convention in projects/box2/project.yaml.
//
// Stated design: length 100 mm, width 200 mm, height 300 mm. The requirements
// below are that envelope, one upper bound per dimension -- the same shape as
// MaxLength in motor_housing.sysml, and within what the extractor reads today
// (one comparison, one literal, one unit per requirement).
//
// Which CAD axis carries which dimension is NOT stated here. SysML says
// "length"; the mapping (projects/box2/mapping.yaml) says which bounding-box
// axis stands for it. That split is deliberate: see the note there.
//
// This file must stay in step with notebooks/04_publish_box2.ipynb -- the
// notebook is what reaches the server.
package Box2 {
    private import ScalarValues::*;
    private import ISQ::*;
    private import SI::*;

    part def Box {
        attribute length : LengthValue;
        attribute width  : LengthValue;
        attribute height : LengthValue;
    }

    requirement def MaxLength {
        doc /* The box must not exceed 100 mm in length. */
        subject box : Box;
        attribute maxLength : LengthValue = 100 [mm];
        require constraint { box.length <= maxLength }
    }

    requirement def MaxWidth {
        doc /* The box must not exceed 200 mm in width. */
        subject box : Box;
        attribute maxWidth : LengthValue = 200 [mm];
        require constraint { box.width <= maxWidth }
    }

    requirement def MaxHeight {
        doc /* The box must not exceed 300 mm in height. */
        subject box : Box;
        attribute maxHeight : LengthValue = 300 [mm];
        require constraint { box.height <= maxHeight }
    }

    part box2 : Box;

    requirement lengthCheck : MaxLength;
    requirement widthCheck  : MaxWidth;
    requirement heightCheck : MaxHeight;

    satisfy lengthCheck by box2;
    satisfy widthCheck  by box2;
    satisfy heightCheck by box2;
}
