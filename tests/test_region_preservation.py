from pathlib import Path
import sys

from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from artwork.edit_regions import preserve_outside_regions
from artwork.maker import checked
from studio.maker_routes import public_history, public_request
from core.files import write_json_atomic


def test_all_pixels_outside_selected_regions_remain_unchanged():
    source = Image.new('RGBA', (100, 80))
    source.putdata([(x % 256, y % 256, (x+y) % 256, (x*3+y) % 256) for y in range(80) for x in range(100)])
    generated = Image.new('RGBA', (50, 40), (255, 255, 255, 255))
    regions = [dict(x=.1, y=.25, w=.3, h=.5), dict(x=.6, y=.25, w=.3, h=.5)]
    result = preserve_outside_regions(source, generated, regions)
    assert result.size == source.size and result.mode == 'RGBA'
    for y in range(80):
        for x in range(100):
            if not (20 <= y < 60 and (10 <= x < 40 or 60 <= x < 90)):
                assert result.getpixel((x, y)) == source.getpixel((x, y))
    assert result.getpixel((25, 40)) == (255, 255, 255, 255)


def test_empty_region_set_cannot_replace_the_whole_image():
    with pytest.raises(ValueError):
        preserve_outside_regions(Image.new('RGB', (32, 32)), Image.new('RGB', (32, 32)), [])


def test_a_single_pixel_selection_does_not_silently_disappear():
    source, edited = Image.new('RGB', (100, 100)), Image.new('RGB', (100, 100), 'white')
    result = preserve_outside_regions(source, edited, [dict(x=.5, y=.5, w=.01, h=.01)])
    assert result.getpixel((50, 50)) == (255, 255, 255)
    assert result.getpixel((49, 50)) == (0, 0, 0)


def test_region_closeup_retains_surrounding_context_at_the_image_edge():
    from artwork.edit_regions import region_context
    source = Image.new('RGB', (1000, 800))
    crop, (left, top), local = region_context(source, dict(x=.9, y=.9, w=.1, h=.1))
    assert left+crop.width <= source.width and top+crop.height <= source.height
    assert round(left+local['x']*crop.width) == 900
    assert round(top+local['y']*crop.height) == 720
    assert 0 <= local['x'] < local['x']+local['w'] <= 1


def request(tmp_path):
    Image.new('RGB', (512, 288)).save(tmp_path/'source.png')
    return dict(template='none', prompt='Correct the selected anatomy.', subject='', references=['source.png'],
                model='Qwen/Qwen-Image-2.1', width=512, height=288, folder=str(tmp_path), name='edit',
                format='png')


def test_region_preservation_requires_png(tmp_path):
    value = request(tmp_path)
    value.update(regions=[dict(x=.2, y=.3, w=.1, h=.2)], region_source='source.png', preserve_outside_regions=True)
    assert checked(value, tmp_path)['preserve_outside_regions'] is True
    value['format'] = 'jpeg'
    with pytest.raises(ValueError, match='PNG'):
        checked(value, tmp_path)


def test_saved_request_and_history_keep_region_preservation(tmp_path):
    value = dict(request(tmp_path), request_id='edit', preserve_outside_regions=True,
                 path=str(tmp_path/'source.png'), id='edit')
    write_json_atomic(tmp_path/'history.json', [value])
    for result in (public_request(value), public_history(tmp_path)[0]):
        assert result['preserve_outside_regions'] is True


def test_colour_style_keeps_pale_characters_in_colour_but_respects_monochrome():
    from direction.entities import sheet_prompt
    entity = dict(kind='character', name='Doctor', looks='Pale skin, white coat and dark trousers.')
    assert 'Render in full colour' in sheet_prompt(entity, 'Soft painterly shading and luminous color.')
    assert 'Render in full colour' not in sheet_prompt(entity, 'Monochrome colour scheme, delicate lines.')
