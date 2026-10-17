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


def test_flat_frame_is_blurred(tmp_path):
    v = lavfi_video(tmp_path, "color=c=gray:size=1920x1080:duration=2")
    plan = choose_crop(v, 0, 2)
    assert plan.mode == CropMode.BLURRED and plan.x is None


def test_busy_everywhere_is_blurred(tmp_path):
    v = lavfi_video(tmp_path, "testsrc2=size=1920x1080:duration=2")
    assert choose_crop(v, 0, 2).mode in (CropMode.BLURRED, CropMode.SMART)
