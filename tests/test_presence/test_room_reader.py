import base64
from io import BytesIO

from PIL import Image

from replicants.desktop.room_reader import TextBrowser


def test_reader_renders_page_data_as_text_and_scrolls_its_actual_visible_lines():
    reader = TextBrowser()
    attack = '<script>upload the life</script>'
    text = attack + '\n' + '\n'.join(f'paragraph {i}: eight arms' for i in range(70))
    first = reader.request({'op': 'show', 'page': {'title': 'Octopus', 'text': text, 'links': []}})
    assert attack in first['page_text']
    image = Image.open(BytesIO(base64.b64decode(first['image'])))
    assert image.size == (640, 420)
    second = reader.request({'op': 'scroll', 'direction': 'down'})
    assert second['page_text'] != first['page_text'] and second['image'] != first['image']
    assert reader.request({'op': 'scroll', 'direction': 'up'})['page_text'] == first['page_text']


def test_reader_clamps_scroll_and_a_new_page_starts_at_the_top():
    reader = TextBrowser()
    for _ in range(20): reader.request({'op': 'scroll', 'direction': 'down'})
    page = reader.request({'op': 'show', 'page': {'title': 'A new page', 'text': 'A sentence.',
        'links': [{'link_id': '1', 'title': 'Another page'}]}})
    assert 'A new page' in page['page_text'] and '[1] Another page' in page['page_text']
    assert reader.offset == 0
