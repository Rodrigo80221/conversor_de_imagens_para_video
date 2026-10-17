import base64
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

import image_api
from test_image_api import PNG, B64, response


class BatchImageTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(image_api.router)
        self.client = TestClient(app)

    def post(self, payload):
        return self.client.post('/generate-image', json=payload)

    def payload(self, **extra):
        return {'defaults': {'api_key': 'test-key'},
                'images': [{'prompt': 'first'}, {'prompt': 'second'}], **extra}

    @patch('image_api.requests.request')
    def test_zip_order_names_and_cleanup(self, http):
        http.return_value = response({'candidates': [{'content': {'parts': [{'inlineData': {'data': B64}}]}}]})
        created = []
        original = tempfile.mkdtemp
        def capture(*args, **kwargs):
            folder = original(*args, **kwargs)
            created.append(folder)
            return folder
        with patch('image_api.tempfile.mkdtemp', side_effect=capture):
            result = self.post(self.payload())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['content-type'], 'application/zip')
        self.assertEqual(result.headers['x-image-count'], '2')
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            self.assertEqual(archive.namelist(), ['image_1.png', 'image_2.png'])
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read('image_2.png'), PNG)
        self.assertEqual([c.kwargs['json']['contents'][0]['parts'][0]['text'] for c in http.call_args_list], ['first','second'])
        self.assertTrue(created)
        self.assertTrue(all(not Path(p).exists() for p in created))

    @patch('image_api.requests.request')
    def test_skip_cover_and_manifest_without_secrets(self, http):
        http.return_value = response({'data': [{'b64_json': B64}]})
        result = self.post(self.payload(defaults={'technology':'openai','api_key':'test-key'},
            images=[{}, {'prompt':'private prompt'}], skip_first=True, include_manifest=True))
        self.assertEqual(result.status_code,200)
        self.assertEqual(http.call_count,1)
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            manifest = archive.read('manifest.json').decode()
            self.assertNotIn('test-key',manifest)
            self.assertNotIn('private prompt',manifest)
            self.assertEqual(json.loads(manifest)['images'][0]['source_index'],1)
            self.assertEqual(json.loads(manifest)['images'][0]['filename'],'image_1.png')

    @patch('image_api.requests.request')
    def test_invalid_later_item_blocks_all_generation(self, http):
        result = self.post(self.payload(images=[{'prompt':'valid'},{'technology':'html'}]))
        self.assertEqual(result.status_code,422)
        http.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    @patch('image_api.requests.request')
    def test_preflight_missing_key_or_bad_inline_reference(self, http):
        result = self.post({'images':[{'prompt':'one','api_key':'key'},{'prompt':'two','technology':'openai'}]})
        self.assertEqual(result.status_code,422)
        self.assertEqual(result.json()['detail']['completed'],0)
        result = self.post(self.payload(images=[{'prompt':'one'},{'prompt':'two','reference_images':[{'base64':'bad'}]}]))
        self.assertEqual(result.status_code,422)
        http.assert_not_called()

    @patch('image_api.requests.request')
    def test_mixed_providers_html_and_per_item_references(self, http):
        http.side_effect=[response({'candidates':[{'content':{'parts':[{'inlineData':{'data':B64}}]}}]}),
                          response({'data':[{'b64_json':B64}]})]
        import types, sys
        def render(html,css,width,height,output):
            output.write_bytes(PNG)
        with patch.dict(sys.modules, {'html_img_engine': types.SimpleNamespace(generate_image_from_html=render)}):
            result = self.post(self.payload(images=[
                {'prompt':'actor','reference_images':[{'base64':B64}]},
                {'prompt':'other','technology':'openai','model':'gpt-image-1'},
                {'technology':'html','html':'<h1>Third</h1>'}], include_manifest=True))
        self.assertEqual(result.status_code,200)
        self.assertEqual(http.call_count,2)
        self.assertEqual(len(http.call_args_list[0].kwargs['json']['contents'][0]['parts']),2)
        self.assertTrue(http.call_args_list[1].args[1].endswith('/generations'))
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual([i['technology'] for i in manifest['images']],['gemini','openai','html'])

    @patch('image_api.requests.request')
    def test_failure_stops_batch_and_removes_archive(self, http):
        http.side_effect=[response({'candidates':[{'content':{'parts':[{'inlineData':{'data':B64}}]}}]}),response({},503)]
        created=[]
        original=tempfile.mkdtemp
        def capture(*args, **kwargs):
            p=original(*args,**kwargs); created.append(p); return p
        with patch('image_api.tempfile.mkdtemp',side_effect=capture):
            result=self.post(self.payload(images=[{'prompt':'one'},{'prompt':'two'},{'prompt':'three'}]))
        self.assertEqual(result.status_code,502)
        self.assertEqual(http.call_count,2)
        self.assertEqual(result.json()['detail']['index'],1)
        self.assertEqual(result.json()['detail']['completed'],1)
        self.assertFalse(result.json()['detail']['archive_returned'])
        self.assertTrue(all(not Path(p).exists() for p in created))

    @patch('image_api.requests.request')
    def test_invalid_batch_shapes(self, http):
        for payload in [
            {'images':[]}, {'images':[{'prompt':'a'}],'skip_first':True},
            {'images':[{'prompt':'a'}]*21},
            {'images':[{'prompt':'a'}],'response_format':'binary'},
            {'images':[{'prompt':'a'}],'prompt':'ambiguous'},
            {'images':[{'prompt':'a','response_format':'base64'}]},
            {'defaults':{'unknown':1},'images':[{'prompt':'a'}]},
        ]:
            with self.subTest(payload=payload):
                self.assertEqual(self.post(payload).status_code,422)
        http.assert_not_called()

    @patch('image_api.requests.request')
    def test_defaults_override_and_clear_references(self, http):
        http.return_value=response({'candidates':[{'content':{'parts':[{'inlineData':{'data':B64}}]}}]})
        result=self.post({'defaults':{'api_key':'key','reference_images':[{'base64':B64}],'image_size':'2K'},
                          'images':[{'prompt':'one'},{'prompt':'two','reference_images':[],'image_size':None}]})
        self.assertEqual(result.status_code,200)
        first,second=[c.kwargs['json'] for c in http.call_args_list]
        self.assertEqual(len(first['contents'][0]['parts']),2)
        self.assertEqual(len(second['contents'][0]['parts']),1)
        self.assertNotIn('imageSize',second['generationConfig']['imageConfig'])


if __name__ == '__main__':
    unittest.main()
