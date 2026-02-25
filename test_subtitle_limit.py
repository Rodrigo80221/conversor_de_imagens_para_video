from pathlib import Path
from video_engine import process_srt_limit_lines

srt_sample = """1
00:00:01,000 --> 00:00:05,000
Line 1
Line 2
Line 3
Line 4

2
00:00:06,000 --> 00:00:08,000
Line A
Line B
"""

# Path setup
test_file = Path("test_limit.srt")
test_file.write_text(srt_sample, encoding='utf-8')

print("Before:")
print(test_file.read_text(encoding='utf-8'))

try:
    # Run limit 2 lines
    process_srt_limit_lines(test_file, 2)

    print("\nAfter (Max 2):")
    print(test_file.read_text(encoding='utf-8'))
except Exception as e:
    print(f"Error: {e}")
