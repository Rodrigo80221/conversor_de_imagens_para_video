"""Timing regressions without loading unrelated Whisper/transformers models."""
import ast
import asyncio
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import types
import unittest
from typing import Optional
from unittest.mock import Mock, patch

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from subtitle_timing import SubtitleTimingError, validate_srt_timings


def load_functions(file, names, namespace):
    tree = ast.parse(Path(__file__).with_name(file).read_text(encoding='utf-8'))
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    exec(compile(ast.Module(body=selected, type_ignores=[]), file, 'exec'), namespace)


GOOD = '1\n00:00:09,640 --> 00:00:10,099\na\n\n2\n00:00:10,099 --> 00:00:10,740\n<highlight>importância</highlight>\n'
BAD = GOOD.replace('00:00:09,640 --> 00:00:10,099', '00:00:09,640 --> 00:10:09,099')


class SubtitleTimingTests(unittest.TestCase):
    def test_reported_typo_identifies_cue_and_next_start(self):
        with self.assertRaises(SubtitleTimingError) as caught:
            validate_srt_timings(BAD)
        self.assertEqual(caught.exception.cue, 1)
        self.assertIn('609.099s', str(caught.exception))
        self.assertIn('10.099s', str(caught.exception))

    def test_corrected_adjacent_cues_and_highlights(self):
        result = validate_srt_timings(GOOD, 12)
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0]['end'], 10.099)
        self.assertIn('<highlight>', GOOD)

    def test_format_order_duration_and_empty_are_rejected(self):
        invalid = ['', 'not srt', GOOD.replace('09,640','69,640'),
                   GOOD.replace('00:00:10,099\na','00:00:09,000\na'),
                   GOOD.replace('00:00:10,099 -->','00:00:08,099 -->')]
        for srt in invalid:
            with self.subTest(srt=srt), self.assertRaises(SubtitleTimingError):
                validate_srt_timings(srt)
        with self.assertRaises(SubtitleTimingError):
            validate_srt_timings(GOOD, 10)

    def test_windows_bom_multiline_and_rounding(self):
        text = '\ufeff1\r\n00:00:00,000 --> 00:00:02,040\r\nLinha 1\r\nLinha 2\r\n'
        self.assertEqual(len(validate_srt_timings(text, 2)), 1)

    def test_route_rejects_before_rendering_and_returns_422(self):
        app = FastAPI()
        engine = Mock()
        namespace = dict(app=app, video_engine=engine, tempfile=tempfile, shutil=shutil, os=__import__('os'), Path=Path,
                         Optional=Optional, UploadFile=UploadFile, File=File, Form=Form, BackgroundTasks=BackgroundTasks,
                         FileResponse=__import__('fastapi.responses', fromlist=['FileResponse']).FileResponse,
                         HTTPException=HTTPException, SubtitleTimingError=SubtitleTimingError,
                         validate_srt_timings=validate_srt_timings)
        load_functions('main.py', {'add_subtitles_endpoint'}, namespace)
        client = TestClient(app)
        result = client.post('/add-subtitles', files={'video_file': ('video.mp4', b'invalid video')}, data={'subtitle_content': BAD})
        self.assertEqual(result.status_code, 422)
        self.assertEqual(result.json()['detail']['cue'], 1)
        engine.add_subtitles.assert_not_called()

    def test_engine_validates_before_reflow_and_ffmpeg(self):
        namespace = dict(Path=Path, Optional=Optional, validate_srt_timings=validate_srt_timings, subprocess=Mock(), json=json)
        load_functions('video_engine.py', {'add_subtitles'}, namespace)
        with tempfile.TemporaryDirectory() as folder:
            srt = Path(folder)/'input.srt'
            srt.write_text(BAD, encoding='utf-8')
            with self.assertRaises(SubtitleTimingError):
                namespace['add_subtitles'](Path(folder)/'in.mp4', srt, Path(folder)/'out.mp4', max_lines=1)
            namespace['subprocess'].run.assert_not_called()

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_valid_srt_burns_and_longer_srt_is_rejected(self):
        namespace = dict(Path=Path, Optional=Optional, re=re, json=json, subprocess=subprocess,
                         validate_srt_timings=validate_srt_timings,
                         _SUBTITLE_DEFAULTS={'font_family':'Arial','font_weight':700,'border_width':1,'font_opacity':100,
                                            'shadow_enabled':False,'shadow_opacity':40,'shadow_depth':1,'highlight_color':'#FFD633'})
        load_functions('video_engine.py', {'add_subtitles','get_video_dimensions','_resolve_subtitle_param','color_to_ass','process_highlight_tags'}, namespace)
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            video, srt, output = folder/'input.mp4', folder/'sub.srt', folder/'out.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=black:s=160x240:d=1.5','-c:v','libx264',str(video)],check=True,capture_output=True)
            srt.write_text('1\n00:00:00,100 --> 00:00:01,000\n<highlight>Teste</highlight>\n',encoding='utf-8')
            namespace['add_subtitles'](video,srt,output,font_family='Arial')
            self.assertGreater(output.stat().st_size, 0)
            self.assertIn('<font color=',srt.read_text(encoding='utf-8'))
            srt.write_text(GOOD,encoding='utf-8')
            with self.assertRaises(SubtitleTimingError):
                namespace['add_subtitles'](video,srt,output)


if __name__ == '__main__':
    unittest.main()
