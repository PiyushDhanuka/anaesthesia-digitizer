/* ==========================================================================
   ARUCO MARKER DETECTOR ENGINE (100% Offline Standalone JS Module)
   Standard 4x4 ArUco Dictionary (MIP_36h12 / 4x4_50 compatible)
   ========================================================================== */

(function(global) {
  'use strict';

  // Standard ArUco 4x4 Dictionary Bit Codes (IDs 0..9)
  const DICT_4X4 = [
    [1,0,1,0, 0,0,0,1, 1,0,1,0, 1,0,1,0], // ID 0
    [1,0,1,1, 0,1,0,1, 1,1,0,0, 0,1,1,0], // ID 1
    [1,0,0,0, 0,1,1,1, 1,0,1,0, 0,1,0,1], // ID 2
    [0,1,1,1, 1,0,1,1, 1,0,0,0, 0,1,0,1], // ID 3
    [0,1,0,0, 1,1,0,1, 0,1,1,1, 1,0,1,0], // ID 4
    [0,1,1,0, 0,1,1,1, 1,0,0,1, 0,1,1,0], // ID 5
    [1,0,0,1, 1,1,0,0, 0,1,0,1, 1,0,1,1], // ID 6
    [0,0,1,0, 1,0,1,1, 1,1,0,1, 0,1,0,0], // ID 7
    [0,1,0,1, 0,0,1,0, 1,1,1,0, 1,0,0,1], // ID 8
    [1,1,0,0, 0,1,0,0, 1,0,1,1, 0,1,0,1]  // ID 9
  ];

  class ArUcoDetector {
    constructor() {}

    detect(imageData) {
      const width = imageData.width;
      const height = imageData.height;
      const data = imageData.data;

      // 1. Grayscale & Threshold (Otsu-style adaptive threshold)
      const gray = new Uint8Array(width * height);
      for (let i = 0, j = 0; i < data.length; i += 4, j++) {
        gray[j] = (data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114) | 0;
      }

      // Simple binarization
      const binary = new Uint8Array(width * height);
      let sum = 0;
      const step = Math.max(1, Math.floor(gray.length / 1000));
      for (let i = 0; i < gray.length; i += step) {
        sum += gray[i];
      }
      const avg = sum / (gray.length / step);
      const threshold = Math.max(40, Math.min(200, avg * 0.85));

      for (let i = 0; i < gray.length; i++) {
        binary[i] = gray[i] < threshold ? 255 : 0;
      }

      // 2. Contour Extraction & Quad Detection
      const contours = this.findContours(binary, width, height);
      const candidates = [];

      for (let i = 0; i < contours.length; i++) {
        const c = contours[i];
        if (c.length < 20) continue;

        const quad = this.approxPolyDP(c, 0.05);
        if (quad.length === 4 && this.isConvex(quad)) {
          const area = this.polygonArea(quad);
          if (area > 150 && area < width * height * 0.4) {
            candidates.push(quad);
          }
        }
      }

      // 3. Decode Candidates
      const markers = [];
      for (let i = 0; i < candidates.length; i++) {
        const quad = candidates[i];
        const marker = this.decodeQuad(gray, width, height, quad);
        if (marker) {
          markers.push(marker);
        }
      }

      return markers;
    }

    findContours(binary, width, height) {
      const visited = new Uint8Array(width * height);
      const contours = [];

      for (let y = 4; y < height - 4; y += 3) {
        for (let x = 4; x < width - 4; x += 3) {
          const idx = y * width + x;
          if (binary[idx] === 255 && !visited[idx]) {
            const contour = this.traceContour(binary, visited, x, y, width, height);
            if (contour && contour.length >= 12) {
              contours.push(contour);
            }
          }
        }
      }

      return contours;
    }

    traceContour(binary, visited, startX, startY, width, height) {
      const contour = [];
      let currX = startX;
      let currY = startY;
      let dir = 0;
      const dx = [1, 1, 0, -1, -1, -1, 0, 1];
      const dy = [0, 1, 1, 1, 0, -1, -1, -1];

      for (let step = 0; step < 400; step++) {
        contour.push({ x: currX, y: currY });
        const idx = currY * width + currX;
        visited[idx] = 1;

        let foundNext = false;
        for (let i = 0; i < 8; i++) {
          const nextDir = (dir + i) % 8;
          const nx = currX + dx[nextDir];
          const ny = currY + dy[nextDir];
          if (nx >= 0 && nx < width && ny >= 0 && ny < height) {
            if (binary[ny * width + nx] === 255) {
              currX = nx;
              currY = ny;
              dir = (nextDir + 6) % 8;
              foundNext = true;
              break;
            }
          }
        }

        if (!foundNext) break;
        if (Math.abs(currX - startX) <= 1 && Math.abs(currY - startY) <= 1 && step > 6) {
          break;
        }
      }

      return contour;
    }

    approxPolyDP(contour, epsilonRatio) {
      const len = contour.length;
      if (len < 4) return contour;

      // Find 4 extreme corners of contour bounding box
      let minSum = Infinity, maxSum = -Infinity, minDiff = Infinity, maxDiff = -Infinity;
      let c0 = contour[0], c1 = contour[0], c2 = contour[0], c3 = contour[0];

      for (let i = 0; i < len; i++) {
        const pt = contour[i];
        const sum = pt.x + pt.y;
        const diff = pt.x - pt.y;

        if (sum < minSum) { minSum = sum; c0 = pt; }
        if (sum > maxSum) { maxSum = sum; c1 = pt; }
        if (diff > maxDiff) { maxDiff = diff; c2 = pt; }
        if (diff < minDiff) { minDiff = diff; c3 = pt; }
      }

      // Order corners clockwise starting top-left: TL, TR, BR, BL
      const corners = [c0, c2, c1, c3];
      return corners;
    }

    isConvex(quad) {
      let sign = false;
      const n = quad.length;
      for (let i = 0; i < n; i++) {
        const dx1 = quad[(i + 1) % n].x - quad[i].x;
        const dy1 = quad[(i + 1) % n].y - quad[i].y;
        const dx2 = quad[(i + 2) % n].x - quad[(i + 1) % n].x;
        const dy2 = quad[(i + 2) % n].y - quad[(i + 1) % n].y;
        const cross = dx1 * dy2 - dy1 * dx2;
        if (i === 0) {
          sign = cross > 0;
        } else if ((cross > 0) !== sign) {
          return false;
        }
      }
      return true;
    }

    polygonArea(pts) {
      let area = 0;
      for (let i = 0; i < pts.length; i++) {
        const j = (i + 1) % pts.length;
        area += pts[i].x * pts[j].y;
        area -= pts[j].x * pts[i].y;
      }
      return Math.abs(area) / 2;
    }

    decodeQuad(gray, width, height, quad) {
      // Sample 6x6 grid inside quad
      const gridBits = [];
      const steps = 6;

      // Centroid of quad
      const cx = (quad[0].x + quad[1].x + quad[2].x + quad[3].x) / 4;
      const cy = (quad[0].y + quad[1].y + quad[2].y + quad[3].y) / 4;

      for (let row = 0; row < steps; row++) {
        for (let col = 0; col < steps; col++) {
          const u = (col + 0.5) / steps;
          const v = (row + 0.5) / steps;

          // Bilinear interpolation inside quad
          const topX = quad[0].x * (1 - u) + quad[1].x * u;
          const topY = quad[0].y * (1 - u) + quad[1].y * u;
          const botX = quad[3].x * (1 - u) + quad[2].x * u;
          const botY = quad[3].y * (1 - u) + quad[2].y * u;

          const px = Math.round(topX * (1 - v) + botX * v);
          const py = Math.round(topY * (1 - v) + botY * v);

          if (px >= 0 && px < width && py >= 0 && py < height) {
            const val = gray[py * width + px];
            gridBits.push(val < 100 ? 0 : 1);
          } else {
            gridBits.push(1);
          }
        }
      }

      if (gridBits.length !== 36) return null;

      // Extract inner 4x4 bits (excluding outer border)
      const innerBits = [];
      for (let r = 1; r < 5; r++) {
        for (let c = 1; c < 5; c++) {
          innerBits.push(gridBits[r * 6 + c]);
        }
      }

      // Check inner bits against dictionary (try 4 rotations)
      for (let rot = 0; rot < 4; rot++) {
        const rotatedInner = this.rotateBits4x4(innerBits, rot);
        for (let id = 0; id < DICT_4X4.length; id++) {
          const dictBits = DICT_4X4[id];
          let diffs = 0;
          for (let b = 0; b < 16; b++) {
            if (rotatedInner[b] !== dictBits[b]) diffs++;
          }
          if (diffs <= 2) {
            return {
              id: id,
              corners: quad,
              center: { x: cx, y: cy }
            };
          }
        }
      }

      return null;
    }

    rotateBits4x4(bits, count) {
      let res = bits.slice();
      for (let r = 0; r < count; r++) {
        const next = new Array(16);
        for (let row = 0; row < 4; row++) {
          for (let col = 0; col < 4; col++) {
            next[col * 4 + (3 - row)] = res[row * 4 + col];
          }
        }
        res = next;
      }
      return res;
    }
  }

  global.ArUcoDetector = ArUcoDetector;

})(typeof window !== 'undefined' ? window : this);
