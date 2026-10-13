# Third-party notices

## Genjutsu — Open Source Workflow

Parts of this project are adapted from
[sirioberati/Genjustsu-Open-Source-Workflow](https://github.com/sirioberati/Genjustsu-Open-Source-Workflow):
the Enhancor/Seedance request shapes and draft → approved-1080p flow
(`motionworkflow/providers/enhancor.py`, `motionworkflow/workflows/swap.py`), the
public media-host uploader (`motionworkflow/hosting.py`), the callback-only webhook
tunnel (`motionworkflow/webhook.py`), and the rule of restoring the source's complete
original audio on swap results. No TEIN names, artwork or example media are included.

    MIT License
    Copyright (c) 2026 Sirio Berati

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

## Services and models

Hosted models (fal.ai, Replicate, Enhancor/Seedance, Pollinations, Anthropic Claude)
are called with your own keys under each provider's own terms, licenses and content
policies. Check a model's license before using its output commercially.

## Python packages

FastAPI, Uvicorn, python-multipart, Requests, Pillow, and the Anthropic SDK keep their
own licenses. ffmpeg is used as an external program.
