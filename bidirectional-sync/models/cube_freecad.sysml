// CubeFreecad -- the first FreeCAD export:
// projects/cube_freecad/cube_freecad.step, a plain cuboid (node "Cube").
//
// The model is models/box2.sysml verbatim -- same part `box2`, same three
// requirements, same numbers -- except for the package name. The package name
// is the server project name, which is how a project is found BY NAME; a
// second `Box2` would make two projects answer to it.
//
// Stated design: length 100 mm, width 200 mm, height 300 mm, one upper bound
// each. FreeCAD writes them along X, Y, Z (measured: X 100, Y 200, Z 300) --
// the default axis convention, unlike Chili3D's.
//
// This file must stay in step with notebooks/05_publish_cube_freecad.ipynb --
// the notebook is what reaches the server.
package CubeFreecad {
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
