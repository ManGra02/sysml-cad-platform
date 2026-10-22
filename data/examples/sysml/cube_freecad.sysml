// CubeFreecad -- a plain cuboid with three upper bounds and satisfy links.
// From bidirectional-sync/models/cube_freecad.sysml (Vincent Hey, branch merge/bidirectional-sync).
//
// Import (needs the SysML kernel: docker compose -f flexo/docker-compose.yml --profile import up -d):
//   cd backend && uv run python -m app.sysml import-sysml ../data/examples/sysml/cube_freecad.sysml
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
