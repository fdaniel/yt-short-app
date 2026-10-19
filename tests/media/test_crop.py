from shorts.media.crop import CropMode, choose_crop
from tests.helpers import lavfi_video


def test_portrait_source_is_center(tmp_path):
    v = lavfi_video(tmp_path, "testsrc2=size=1080x1920:duration=2")
    assert choose_crop(v, 0, 2).mode == CropMode.CENTER


def test_subject_on_left_is_smart(tmp_path):
    v = lavfi_video(
        tmp_path, "color=c=black:size=1920x1080:duration=2,drawbox=x=150:y=300:w=300:h=400:color=white:t=fill"
    )
    plan = choose_crop(v, 0, 2)
    assert plan.mode == CropMode.SMART and 0 <= plan.x <= 300


def test_subject_on_right_is_smart(tmp_path):
    v = lavfi_video(
        tmp_path, "color=c=black:size=1920x1080:duration=2,drawbox=x=1500:y=300:w=300:h=400:color=white:t=fill"
    )
    plan = choose_crop(v, 0, 2)
    assert plan.mode == CropMode.SMART and 1192 <= plan.x <= 1312


def test_flat_frame_fills_the_screen_from_the_center(tmp_path):
    # never a small strip over a blurred copy: that left most of the screen dark
    v = lavfi_video(tmp_path, "color=c=gray:size=1920x1080:duration=2")
    plan = choose_crop(v, 0, 2)
    assert plan.mode == CropMode.CENTER and plan.x is None


def test_busy_everywhere_fills_the_screen(tmp_path):
    v = lavfi_video(tmp_path, "testsrc2=size=1920x1080:duration=2")
    assert choose_crop(v, 0, 2).mode in (CropMode.CENTER, CropMode.SMART)


LETTERBOXED = (
    "color=c=gray:size=1920x810:duration=2,drawbox=x=150:y=200:w=300:h=400:color=white:t=fill,"
    "pad=1920:1080:0:135:black"
)


def test_letterbox_bars_are_left_out(tmp_path):
    # cinematic trailers carry black bars; cropping them in left black bands on the Short
    plan = choose_crop(lavfi_video(tmp_path, LETTERBOXED), 0, 2)
    assert abs(plan.top - 135) <= 4 and abs(plan.height - 810) <= 8


def test_full_frame_has_no_bars(tmp_path):
    plan = choose_crop(lavfi_video(tmp_path, "testsrc2=size=1920x1080:duration=2"), 0, 2)
    assert plan.top == 0 and plan.height is None


def test_night_sky_is_not_taken_for_a_bar(tmp_path):
    # real letterbox bars come in equal pairs; a dark sky is only at the top
    v = lavfi_video(tmp_path, "color=c=gray:size=1920x1080:duration=2,drawbox=x=0:y=0:w=1920:h=330:color=0x0a0a0a:t=fill")
    assert choose_crop(v, 0, 2).height is None
