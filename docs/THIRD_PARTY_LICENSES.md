# Third-party components

## sparrow (nesting engine, bundled as engines/sparrow.exe)
Source: https://github.com/JeroenGar/sparrow (commit 4629b22795ae6b25b3b460ccde6fb36a71292b6d, unmodified).
Built by the LEVEL7 CI from that commit with the dependency versions in packaging/sparrow/Cargo.lock.

```
MIT License

Copyright (c) 2025 Jeroen Gardeyn, KU Leuven

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
```

## jagua-rs 1.1.0 (used by sparrow; MPL-2.0)
jagua-rs is licensed under the Mozilla Public License 2.0 (https://mozilla.org/MPL/2.0/). It is used unmodified;
its source code is available at https://github.com/JeroenGar/jagua-rs and https://crates.io/crates/jagua-rs/1.1.0 .

## Other Rust crates compiled into sparrow
Licensed under MIT and/or Apache-2.0 (or Zlib / Unlicense alternatives); the exact list and versions are in
packaging/sparrow/Cargo.lock. Their licence texts are available from https://crates.io for each crate.

## Python packages bundled in the installer
See DEPENDENCIES.md (PySide6/Qt under LGPL-3.0, shapely, pyclipper, ezdxf, numpy …).
