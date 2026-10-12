// Camera Capture and Calibration Tool - Complete Application

const API_BASE = (window.location.protocol && window.location.protocol.startsWith('http') && window.location.origin && window.location.origin !== 'null')
  ? window.location.origin
  : 'http://localhost:8000';

document.addEventListener('DOMContentLoaded', () => {
  // DOM Elements
  const webcamFeed = document.getElementById('webcamFeed');
  const freezeCanvas = document.getElementById('freezeCanvas');
  const freezeBtn = document.getElementById('freezeBtn');
  const freezeBtnText = document.getElementById('freezeBtnText');
  const retakeBtn = document.getElementById('retakeBtn');
  const undoBtn = document.getElementById('undoBtn');
  const resetBtn = document.getElementById('resetBtn');
  const saveBtn = document.getElementById('saveBtn');
  const downloadBtn = document.getElementById('downloadBtn');
  const stepBadge = document.getElementById('stepBadge');
  const stepTitle = document.getElementById('stepTitle');
  const cameraError = document.getElementById('cameraError');
  const retryCameraBtn = document.getElementById('retryCameraBtn');
  const cameraSelect = document.getElementById('cameraSelect');
  const screenShareBtn = document.getElementById('screenShareBtn');
  const simulatedFeedBtn = document.getElementById('simulatedFeedBtn');
  const errorScreenShareBtn = document.getElementById('errorScreenShareBtn');
  const errorSimulatedBtn = document.getElementById('errorSimulatedBtn');
  const errorIcon = document.getElementById('errorIcon');
  const errorTitle = document.getElementById('errorTitle');
  const errorMessage = document.getElementById('errorMessage');
  const errorDiagnosticHint = document.getElementById('errorDiagnosticHint');
  const statusBadge = document.getElementById('statusBadge');
  const statusText = document.getElementById('statusText');
  const actualResText = document.getElementById('actualResText');
  const markedCount = document.getElementById('markedCount');
  const checklistGroup = document.getElementById('checklistGroup');
  
  // Stepper Elements
  const stepNode1 = document.getElementById('stepNode1');
  const stepNode2 = document.getElementById('stepNode2');
  const stepNode3 = document.getElementById('stepNode3');
  const stepNode4 = document.getElementById('stepNode4');
  const connector1 = document.getElementById('connector1');
  const connector2 = document.getElementById('connector2');
  const connector3 = document.getElementById('connector3');

  // Banner Elements
  const saveSuccessBanner = document.getElementById('saveSuccessBanner');
  const bannerTitle = document.getElementById('bannerTitle');
  const bannerText = document.getElementById('bannerText');
  const closeBannerBtn = document.getElementById('closeBannerBtn');

  // Modal Elements
  const labelModal = document.getElementById('labelModal');
  const labelOptBtns = document.querySelectorAll('.label-opt-btn');
  const cancelLabelBtn = document.getElementById('cancelLabelBtn');

  // Application State
  let mediaStream = null;
  let simulatedAnimationId = null;
  let isFrozen = false;
  let isDrawing = false;
  let startX = 0, startY = 0, currentX = 0, currentY = 0;
  let pendingBox = null;
  let boxes = [];

  // Offscreen canvas for storing snapshot of frozen frame
  const offscreenCanvas = document.createElement('canvas');
  const offscreenCtx = offscreenCanvas.getContext('2d');

  const TARGET_WIDTH = 1280;
  const TARGET_HEIGHT = 720;

  // Stop any existing stream or active simulation
  function stopActiveStream() {
    if (simulatedAnimationId) {
      cancelAnimationFrame(simulatedAnimationId);
      simulatedAnimationId = null;
    }
    if (mediaStream) {
      mediaStream.getTracks().forEach(track => track.stop());
      mediaStream = null;
    }
  }

  // Populate available video input devices in camera dropdown
  async function populateCameraDevices() {
    if (!cameraSelect || !navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const videoDevices = devices.filter(device => device.kind === 'videoinput');
      
      const currentVal = cameraSelect.value;
      cameraSelect.innerHTML = '<option value="">Default Camera</option>';
      
      videoDevices.forEach((device, idx) => {
        const option = document.createElement('option');
        option.value = device.deviceId;
        option.textContent = device.label || `Camera ${idx + 1} (${device.deviceId.slice(0, 6)}...)`;
        cameraSelect.appendChild(option);
      });
      if (currentVal) cameraSelect.value = currentVal;
    } catch (e) {
      console.warn('Could not enumerate camera devices:', e);
    }
  }

  // Initialize Camera Access via getUserMedia with constraint fallbacks
  async function initCamera(selectedDeviceId = null) {
    stopActiveStream();
    hideError();
    if (webcamFeed) webcamFeed.classList.remove('hidden');
    if (freezeCanvas) freezeCanvas.classList.add('hidden');
    updateStatus('connecting', 'Connecting camera...');
    freezeBtn.disabled = true;

    // Check secure context / mediaDevices support
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      const isFileProtocol = window.location.protocol === 'file:';
      const isHttpNonLocal = window.location.protocol === 'http:' && 
                             window.location.hostname !== 'localhost' && 
                             window.location.hostname !== '127.0.0.1';
      
      const errReason = isFileProtocol || isHttpNonLocal
        ? 'InsecureContext'
        : 'NotSupported';

      const customErr = new Error('MediaDevices API not available in this context');
      customErr.name = errReason;
      showError(customErr);
      return;
    }

    const targetDeviceId = selectedDeviceId || (cameraSelect ? cameraSelect.value : null);

    try {
      // Stage 1: Try exact target deviceId or ideal resolution constraints
      try {
        const constraints = targetDeviceId
          ? { video: { deviceId: { exact: targetDeviceId } }, audio: false }
          : { video: { width: { ideal: TARGET_WIDTH }, height: { ideal: TARGET_HEIGHT } }, audio: false };
        mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
      } catch (e1) {
        console.warn('Stage 1 camera constraints failed, attempting stage 2 basic video constraint...', e1);
        try {
          // Stage 2: Basic video constraint without fixed resolution or deviceId restriction
          mediaStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        } catch (e2) {
          console.warn('Stage 2 failed, attempting stage 3 minimal video constraint...', e2);
          // Stage 3: Bare minimal video constraint fallback
          mediaStream = await navigator.mediaDevices.getUserMedia({ video: {} });
        }
      }

      webcamFeed.srcObject = mediaStream;

      const handleCameraMetadata = () => {
        webcamFeed.play().catch(e => console.warn('Autoplay prevented:', e));
        const width = webcamFeed.videoWidth || TARGET_WIDTH;
        const height = webcamFeed.videoHeight || TARGET_HEIGHT;
        actualResText.textContent = `Feed Resolution: ${width} × ${height} px`;
        
        freezeCanvas.width = width;
        freezeCanvas.height = height;
        offscreenCanvas.width = width;
        offscreenCanvas.height = height;

        updateStatus('live', 'Live Feed');
        if (!isMonitoring && !window._activeCaseId) {
          updateTopCaseStatus('camera_live', null);
        }
        freezeBtn.disabled = false;
        updateStepper();
        populateCameraDevices();
      };

      if (webcamFeed.readyState >= 1) {
        handleCameraMetadata();
      } else {
        webcamFeed.onloadedmetadata = handleCameraMetadata;
      }
      webcamFeed.play().catch(e => console.warn('Camera play attempt:', e));

    } catch (err) {
      console.error('Error accessing webcam:', err);
      showError(err);
    }
  }

  // Fallback Mode 1: Screen Share (getDisplayMedia)
  async function initScreenShare() {
    stopActiveStream();
    hideError();
    if (webcamFeed) webcamFeed.classList.remove('hidden');
    if (freezeCanvas) freezeCanvas.classList.add('hidden');
    updateStatus('connecting', 'Sharing screen...');
    freezeBtn.disabled = true;

    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
      alert('Screen sharing is not supported in this browser.');
      return;
    }

    try {
      mediaStream = await navigator.mediaDevices.getDisplayMedia({
        video: { cursor: 'always' },
        audio: false
      });

      webcamFeed.srcObject = mediaStream;

      const handleScreenMetadata = () => {
        webcamFeed.play().catch(e => console.warn('Autoplay prevented:', e));
        const width = webcamFeed.videoWidth || TARGET_WIDTH;
        const height = webcamFeed.videoHeight || TARGET_HEIGHT;
        actualResText.textContent = `Feed Resolution: ${width} × ${height} px (Screen Share)`;

        freezeCanvas.width = width;
        freezeCanvas.height = height;
        offscreenCanvas.width = width;
        offscreenCanvas.height = height;

        updateStatus('live', 'Screen Share');
        if (!isMonitoring && !window._activeCaseId) {
          updateTopCaseStatus('camera_live', null);
        }
        freezeBtn.disabled = false;
        updateStepper();
      };

      if (webcamFeed.readyState >= 1) {
        handleScreenMetadata();
      } else {
        webcamFeed.onloadedmetadata = handleScreenMetadata;
      }
      webcamFeed.play().catch(e => console.warn('Play attempt:', e));

      // Listen for stream end (user clicks "Stop Sharing")
      mediaStream.getVideoTracks()[0].onended = () => {
        updateStatus('connecting', 'Screen share ended');
        showError({ name: 'Ended', message: 'Screen sharing session was ended.' });
      };

    } catch (err) {
      console.warn('Screen share canceled or failed:', err);
      if (err.name !== 'NotAllowedError') {
        showError(err);
      } else {
        updateStatus('error', 'Canceled');
      }
    }
  }

  function getDefaultDemoCalibration() {
    return {
      timestamp: new Date().toISOString(),
      frameWidth: TARGET_WIDTH,
      frameHeight: TARGET_HEIGHT,
      regions: {
        heartRate: { x: 25, y: 80, width: 160, height: 90, color: '#34D399' },
        spo2: { x: 25, y: 230, width: 160, height: 90, color: '#38BDF8' },
        bloodPressure: { x: 25, y: 380, width: 230, height: 90, color: '#F87171' },
        etco2: { x: 25, y: 530, width: 160, height: 90, color: '#EAB93F' }
      },
      markers: {}
    };
  }

  // Fallback Mode 2: Simulated Patient Monitor Feed (Canvas Generator)
  function initSimulatedFeed() {
    stopActiveStream();
    hideError();
    
    if (webcamFeed) webcamFeed.classList.remove('hidden');
    if (freezeCanvas) freezeCanvas.classList.add('hidden');
    
    updateStatus('live', 'Demo Monitor');
    if (!isMonitoring && !window._activeCaseId) {
      updateTopCaseStatus('camera_live', null);
    }
    freezeBtn.disabled = false;

    if (!localStorage.getItem('monitorCalibration')) {
      const defaultCalib = getDefaultDemoCalibration();
      localStorage.setItem('monitorCalibration', JSON.stringify(defaultCalib));
    }

    const simCanvas = document.createElement('canvas');
    simCanvas.width = TARGET_WIDTH;
    simCanvas.height = TARGET_HEIGHT;
    const simCtx = simCanvas.getContext('2d');

    let waveOffset = 0;

    function renderSimulatedFrame() {
      waveOffset += 0.05;

      // Dark medical screen background
      simCtx.fillStyle = '#090d16';
      simCtx.fillRect(0, 0, TARGET_WIDTH, TARGET_HEIGHT);

      // Header Bar
      simCtx.fillStyle = '#1e293b';
      simCtx.fillRect(0, 0, TARGET_WIDTH, 48);
      simCtx.fillStyle = '#94a3b8';
      simCtx.font = '600 16px Inter, sans-serif';
      simCtx.fillText('PATIENT MONITOR - SIMULATOR FEED (OR-ROOM 3)', 20, 30);
      simCtx.fillStyle = '#10b981';
      simCtx.fillText('● MONITORED', TARGET_WIDTH - 160, 30);

      // Grid Lines
      simCtx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
      simCtx.lineWidth = 1;
      for (let x = 0; x < TARGET_WIDTH; x += 40) {
        simCtx.beginPath(); simCtx.moveTo(x, 48); simCtx.lineTo(x, TARGET_HEIGHT); simCtx.stroke();
      }
      for (let y = 48; y < TARGET_HEIGHT; y += 40) {
        simCtx.beginPath(); simCtx.moveTo(0, y); simCtx.lineTo(TARGET_WIDTH, y); simCtx.stroke();
      }

      // Vital 1: Heart Rate (Green)
      simCtx.fillStyle = '#10b981';
      simCtx.font = 'bold 18px Inter, sans-serif';
      simCtx.fillText('ECG / HR', 30, 90);
      simCtx.font = 'bold 64px Inter, sans-serif';
      simCtx.fillText('74', 30, 160);
      simCtx.font = '14px Inter, sans-serif';
      simCtx.fillText('bpm', 120, 160);

      // ECG Waveform
      simCtx.strokeStyle = '#10b981';
      simCtx.lineWidth = 3;
      simCtx.beginPath();
      for (let x = 200; x < TARGET_WIDTH - 30; x += 2) {
        const t = (x / 50) - waveOffset;
        let y = 130 + Math.sin(t) * 8;
        const cycle = (x + waveOffset * 60) % 180;
        if (cycle > 80 && cycle < 90) y -= 45;
        else if (cycle >= 90 && cycle < 100) y += 15;
        if (x === 200) simCtx.moveTo(x, y); else simCtx.lineTo(x, y);
      }
      simCtx.stroke();

      // Divider
      simCtx.strokeStyle = '#334155';
      simCtx.beginPath(); simCtx.moveTo(20, 200); simCtx.lineTo(TARGET_WIDTH - 20, 200); simCtx.stroke();

      // Vital 2: SpO2 (Cyan)
      simCtx.fillStyle = '#0284c7';
      simCtx.font = 'bold 18px Inter, sans-serif';
      simCtx.fillText('SpO2', 30, 240);
      simCtx.font = 'bold 64px Inter, sans-serif';
      simCtx.fillText('98', 30, 310);
      simCtx.font = '14px Inter, sans-serif';
      simCtx.fillText('%', 120, 310);

      // Pleth Waveform
      simCtx.strokeStyle = '#0284c7';
      simCtx.lineWidth = 3;
      simCtx.beginPath();
      for (let x = 200; x < TARGET_WIDTH - 30; x += 3) {
        const t = (x / 40) - waveOffset;
        let y = 280 + Math.sin(t) * 18 + Math.cos(t * 2) * 5;
        if (x === 200) simCtx.moveTo(x, y); else simCtx.lineTo(x, y);
      }
      simCtx.stroke();

      // Divider
      simCtx.beginPath(); simCtx.moveTo(20, 350); simCtx.lineTo(TARGET_WIDTH - 20, 350); simCtx.stroke();

      // Vital 3: NIBP Blood Pressure (Orange)
      simCtx.fillStyle = '#d97706';
      simCtx.font = 'bold 18px Inter, sans-serif';
      simCtx.fillText('NIBP (Sys / Dia)', 30, 390);
      simCtx.font = 'bold 60px Inter, sans-serif';
      simCtx.fillText('120/80', 30, 460);
      simCtx.font = '14px Inter, sans-serif';
      simCtx.fillText('mmHg  (Mean 93)', 260, 460);

      // Divider
      simCtx.beginPath(); simCtx.moveTo(20, 500); simCtx.lineTo(TARGET_WIDTH - 20, 500); simCtx.stroke();

      // Vital 4: EtCO2 (Purple)
      simCtx.fillStyle = '#8b5cf6';
      simCtx.font = 'bold 18px Inter, sans-serif';
      simCtx.fillText('EtCO2', 30, 540);
      simCtx.font = 'bold 64px Inter, sans-serif';
      simCtx.fillText('36', 30, 610);
      simCtx.font = '14px Inter, sans-serif';
      simCtx.fillText('mmHg', 120, 610);

      // Capnography Waveform
      simCtx.strokeStyle = '#8b5cf6';
      simCtx.lineWidth = 3;
      simCtx.beginPath();
      for (let x = 200; x < TARGET_WIDTH - 30; x += 4) {
        const cycle = (x + waveOffset * 40) % 200;
        let y = 600;
        if (cycle > 40 && cycle < 140) y = 560 + Math.sin(x / 30) * 3;
        if (x === 200) simCtx.moveTo(x, y); else simCtx.lineTo(x, y);
      }
      simCtx.stroke();

      // Always populate offscreenCanvas
      offscreenCanvas.width = TARGET_WIDTH;
      offscreenCanvas.height = TARGET_HEIGHT;
      offscreenCtx.drawImage(simCanvas, 0, 0);

      simulatedAnimationId = requestAnimationFrame(renderSimulatedFrame);
    }

    renderSimulatedFrame();

    try {
      const stream = simCanvas.captureStream(30);
      mediaStream = stream;
      webcamFeed.srcObject = mediaStream;
      webcamFeed.play().catch(e => console.warn('Simulated video play prevented:', e));
    } catch (e) {
      console.warn('Canvas captureStream not supported/allowed in this browser:', e);
    }

    actualResText.textContent = `Feed Resolution: ${TARGET_WIDTH} × ${TARGET_HEIGHT} px (Demo Feed)`;
    freezeCanvas.width = TARGET_WIDTH;
    freezeCanvas.height = TARGET_HEIGHT;
    updateStepper();
  }

  // Toggle freeze / unfreeze frame
  function toggleFreezeFrame() {
    if (!isFrozen) {
      freezeCurrentFrame();
    } else {
      unfreezeToLiveFeed();
    }
  }

  // Freeze Frame Logic
  function freezeCurrentFrame() {
    const width = (webcamFeed && webcamFeed.videoWidth > 0) ? webcamFeed.videoWidth : (offscreenCanvas.width || TARGET_WIDTH);
    const height = (webcamFeed && webcamFeed.videoHeight > 0) ? webcamFeed.videoHeight : (offscreenCanvas.height || TARGET_HEIGHT);

    freezeCanvas.width = width;
    freezeCanvas.height = height;

    // Capture frozen snapshot from video feed if available
    if (webcamFeed && webcamFeed.videoWidth > 0 && !webcamFeed.paused) {
      try {
        offscreenCanvas.width = width;
        offscreenCanvas.height = height;
        offscreenCtx.drawImage(webcamFeed, 0, 0, width, height);
      } catch (e) {}
    }

    // Switch view visibility
    webcamFeed.classList.add('hidden');
    freezeCanvas.classList.remove('hidden');

    stepBadge.textContent = 'Step 2 & 3';
    stepTitle.textContent = 'Click and drag to draw a box around each vital sign';
    freezeBtnText.textContent = 'Resume Live Feed';
    freezeBtn.classList.remove('btn-primary');
    freezeBtn.classList.add('btn-accent');
    updateStatus('frozen', 'Frame Frozen');

    isFrozen = true;
    retakeBtn.disabled = false;
    updateStepper();
    redrawCanvas();
  }

  // Unfreeze Frame / Resume Live Feed
  function unfreezeToLiveFeed() {
    freezeCanvas.classList.add('hidden');
    webcamFeed.classList.remove('hidden');

    stepBadge.textContent = 'Step 1';
    stepTitle.textContent = 'Point your camera at the monitor screen';
    freezeBtnText.textContent = 'Freeze Frame';
    freezeBtn.classList.remove('btn-accent');
    freezeBtn.classList.add('btn-primary');
    updateStatus('live', 'Live Feed');

    isFrozen = false;
    retakeBtn.disabled = true;
    updateStepper();
  }

  // Retake Frame Action
  function retakeFrame() {
    if (isFrozen) {
      unfreezeToLiveFeed();
    }
  }

  // Get canvas scaled coordinates from mouse event
  function getCanvasCoords(e) {
    const rect = freezeCanvas.getBoundingClientRect();
    const scaleX = freezeCanvas.width / rect.width;
    const scaleY = freezeCanvas.height / rect.height;
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY
    };
  }

  // Mouse Event Handlers for Rectangle Drawing
  freezeCanvas.addEventListener('mousedown', (e) => {
    if (!isFrozen) return;
    isDrawing = true;
    const coords = getCanvasCoords(e);
    startX = coords.x;
    startY = coords.y;
    currentX = coords.x;
    currentY = coords.y;
  });

  freezeCanvas.addEventListener('mousemove', (e) => {
    if (!isDrawing) return;
    const coords = getCanvasCoords(e);
    currentX = coords.x;
    currentY = coords.y;
    redrawCanvas();
    drawPendingRect();
  });

  freezeCanvas.addEventListener('mouseup', () => {
    if (!isDrawing) return;
    isDrawing = false;
    
    const x = Math.min(startX, currentX);
    const y = Math.min(startY, currentY);
    const width = Math.abs(currentX - startX);
    const height = Math.abs(currentY - startY);

    if (width > 20 && height > 20) {
      pendingBox = { x, y, width, height };
      openLabelModal();
    } else {
      redrawCanvas();
    }
  });

  function drawPendingRect() {
    const ctx = freezeCanvas.getContext('2d');
    const x = Math.min(startX, currentX);
    const y = Math.min(startY, currentY);
    const width = Math.abs(currentX - startX);
    const height = Math.abs(currentY - startY);

    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(x, y, width, height);
    ctx.fillStyle = 'rgba(56, 189, 248, 0.15)';
    ctx.fillRect(x, y, width, height);
    ctx.setLineDash([]);
  }

  // Modal Label Selector
  function openLabelModal() {
    updateAvailableLabelOptions();
    labelModal.classList.remove('hidden');
  }

  function closeLabelModal() {
    labelModal.classList.add('hidden');
    pendingBox = null;
    redrawCanvas();
  }

  function updateAvailableLabelOptions() {
    const labeledTypes = boxes.map(b => b.label);
    labelOptBtns.forEach(btn => {
      const label = btn.dataset.label;
      if (labeledTypes.includes(label)) {
        btn.disabled = true;
      } else {
        btn.disabled = false;
      }
    });
  }

  labelOptBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      if (!pendingBox) return;
      const label = btn.dataset.label;
      const color = btn.dataset.color;
      
      boxes.push({
        ...pendingBox,
        label,
        color
      });

      closeLabelModal();
      updateChecklistUI();
      redrawCanvas();
    });
  });

  if (cancelLabelBtn) {
    cancelLabelBtn.addEventListener('click', closeLabelModal);
  }

  // Redraw Canvas Overlay
  function redrawCanvas() {
    const ctx = freezeCanvas.getContext('2d');
    ctx.clearRect(0, 0, freezeCanvas.width, freezeCanvas.height);
    
    if (offscreenCanvas.width > 0 && offscreenCanvas.height > 0) {
      ctx.drawImage(offscreenCanvas, 0, 0);
    }

    boxes.forEach((box, idx) => {
      ctx.strokeStyle = box.color;
      ctx.lineWidth = 3;
      ctx.strokeRect(box.x, box.y, box.width, box.height);

      ctx.fillStyle = box.color;
      ctx.font = 'bold 14px Inter, sans-serif';
      const textMetrics = ctx.measureText(`${idx + 1}. ${box.label}`);
      const bgWidth = textMetrics.width + 16;
      ctx.fillRect(box.x, Math.max(0, box.y - 26), bgWidth, 26);

      ctx.fillStyle = '#ffffff';
      ctx.fillText(`${idx + 1}. ${box.label}`, box.x + 8, Math.max(18, box.y - 8));
    });
  }

  // Undo & Reset Actions
  if (undoBtn) {
    undoBtn.addEventListener('click', () => {
      if (boxes.length > 0) {
        boxes.pop();
        updateChecklistUI();
        redrawCanvas();
      }
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      boxes = [];
      updateChecklistUI();
      redrawCanvas();
    });
  }

  // Save Calibration Data
  if (saveBtn) {
    saveBtn.addEventListener('click', () => {
      if (boxes.length === 0) {
        alert('Please draw at least one region box before saving.');
        return;
      }

      const calibration = {
        timestamp: new Date().toISOString(),
        frameWidth: freezeCanvas.width || TARGET_WIDTH,
        frameHeight: freezeCanvas.height || TARGET_HEIGHT,
        regions: {},
        markers: {}
      };

      boxes.forEach(b => {
        const keyMap = {
          'Heart Rate': 'heartRate',
          'SpO2': 'spo2',
          'Blood Pressure': 'bloodPressure',
          'EtCO2': 'etco2'
        };
        const key = keyMap[b.label] || b.label.toLowerCase();
        calibration.regions[key] = {
          x: Math.round(b.x),
          y: Math.round(b.y),
          width: Math.round(b.width),
          height: Math.round(b.height),
          color: b.color
        };
      });

      // Detect and store ArUco anchor marker coordinates if present during calibration
      if (typeof ArUcoDetector !== 'undefined') {
        try {
          const detector = new ArUcoDetector();
          const fCtx = freezeCanvas.getContext('2d');
          const imgData = fCtx.getImageData(0, 0, freezeCanvas.width || TARGET_WIDTH, freezeCanvas.height || TARGET_HEIGHT);
          const detectedMarkers = detector.detect(imgData);
          if (detectedMarkers && detectedMarkers.length > 0) {
            detectedMarkers.forEach(m => {
              calibration.markers[m.id] = {
                x: Math.round(m.center.x),
                y: Math.round(m.center.y)
              };
            });
            console.log(`[ARUCO CALIBRATION SUCCESS] Detected and stored ${detectedMarkers.length} anchor markers:`, calibration.markers);
          } else {
            console.log('[ARUCO CALIBRATION NOTE] No ArUco anchor markers detected during calibration. Auto-alignment will run in fixed-ROI mode.');
          }
        } catch (e) {
          console.warn('Error detecting ArUco markers during calibration:', e);
        }
      }

      localStorage.setItem('monitorCalibration', JSON.stringify(calibration));
      console.log('Saved monitor calibration to localStorage:', calibration);
      showSaveSuccessBanner();
      showMonitoringSection();
      startMonitoring();
    });
  }

  // Download Calibration JSON
  if (downloadBtn) {
    downloadBtn.addEventListener('click', () => {
      const savedStr = localStorage.getItem('monitorCalibration');
      if (!savedStr) {
        alert('No calibration data saved yet.');
        return;
      }
      const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(savedStr);
      const dlAnchor = document.createElement('a');
      dlAnchor.setAttribute("href", dataStr);
      dlAnchor.setAttribute("download", "monitor_calibration.json");
      document.body.appendChild(dlAnchor);
      dlAnchor.click();
      dlAnchor.remove();
    });
  }

  function showSaveSuccessBanner() {
    if (saveSuccessBanner) {
      saveSuccessBanner.classList.remove('hidden');
      setTimeout(() => {
        saveSuccessBanner.classList.add('hidden');
      }, 5000);
    }
  }

  if (closeBannerBtn) {
    closeBannerBtn.addEventListener('click', () => {
      if (saveSuccessBanner) saveSuccessBanner.classList.add('hidden');
    });
  }

  // Update Checklist UI & Buttons state
  function updateChecklistUI() {
    markedCount.textContent = `${boxes.length} / 4`;

    const items = [
      { key: 'Heart Rate', id: 'checkHR' },
      { key: 'SpO2', id: 'checkSpO2' },
      { key: 'Blood Pressure', id: 'checkBP' },
      { key: 'EtCO2', id: 'checkEtCO2' }
    ];

    const currentLabels = boxes.map(b => b.label);

    items.forEach(item => {
      const el = document.getElementById(item.id);
      if (!el) return;
      const statusSpan = el.querySelector('.check-status');

      if (currentLabels.includes(item.key)) {
        el.className = 'checklist-item complete';
        if (statusSpan) statusSpan.textContent = '✓ Marked';
      } else {
        el.className = 'checklist-item pending';
        if (statusSpan) statusSpan.textContent = 'Pending';
      }
    });

    if (undoBtn) undoBtn.disabled = boxes.length === 0;
    if (resetBtn) resetBtn.disabled = boxes.length === 0;
    if (saveBtn) saveBtn.disabled = boxes.length === 0;
    if (downloadBtn) downloadBtn.disabled = !localStorage.getItem('monitorCalibration');
  }

  // Stepper Visual Update
  function updateStepper() {
    stepNode1.className = 'step-node';
    stepNode2.className = 'step-node';
    stepNode3.className = 'step-node';
    stepNode4.className = 'step-node';

    if (!isFrozen && boxes.length === 0) {
      stepNode1.classList.add('active');
    } else if (isFrozen && boxes.length === 0) {
      stepNode1.classList.add('complete');
      stepNode2.classList.add('active');
    } else if (isFrozen && boxes.length > 0 && boxes.length < 4) {
      stepNode1.classList.add('complete');
      stepNode2.classList.add('complete');
      stepNode3.classList.add('active');
    } else if (boxes.length >= 4 || localStorage.getItem('monitorCalibration')) {
      stepNode1.classList.add('complete');
      stepNode2.classList.add('complete');
      stepNode3.classList.add('complete');
      stepNode4.classList.add('active');
    }
  }

  // Helper for Status Badge
  function updateStatus(state, label) {
    statusBadge.className = `status-badge status-${state}`;
    statusText.textContent = label;
  }

  // Diagnostic Camera Error Handler
  function showError(err) {
    updateStatus('error', 'Camera Offline');
    cameraError.classList.remove('hidden');

    const errName = err && err.name ? err.name : '';
    const isFile = window.location.protocol === 'file:';
    const isHttpNonLocal = window.location.protocol === 'http:' && 
                           window.location.hostname !== 'localhost' && 
                           window.location.hostname !== '127.0.0.1';

    if (errName === 'InsecureContext' || isFile || isHttpNonLocal) {
      if (errorIcon) errorIcon.textContent = '🔒⚠️';
      if (errorTitle) errorTitle.textContent = 'Browser Security Restriction';
      if (errorMessage) errorMessage.textContent = 'Modern browsers block camera access when opening HTML directly as local files (file://) or over plain HTTP IP addresses.';
      if (errorDiagnosticHint) {
        errorDiagnosticHint.classList.remove('hidden');
        errorDiagnosticHint.innerHTML = `
          <strong>Why this happens & How to test:</strong><br>
          Modern browsers restrict physical webcam access to HTTPS or <code>localhost</code>.<br><br>
          1. <strong>To test over LAN on mobile/iPad:</strong> Click the <strong>Demo Feed (Dev)</strong> button below to test immediate vital sign OCR calibration.<br>
          2. <strong>To use physical camera:</strong> Access the app locally via <a href="${API_BASE}/app/index.html" target="_blank" style="color: #38bdf8; text-decoration: underline;">${API_BASE}/app/index.html</a> or setup an HTTPS proxy.
        `;
      }
    } else if (errName === 'NotAllowedError' || errName === 'PermissionDeniedError') {
      if (errorIcon) errorIcon.textContent = '🚫📷';
      if (errorTitle) errorTitle.textContent = 'Camera Access Blocked';
      if (errorMessage) errorMessage.textContent = 'Permission to access your webcam was denied in browser or system privacy settings.';
      if (errorDiagnosticHint) {
        errorDiagnosticHint.classList.remove('hidden');
        errorDiagnosticHint.innerHTML = `
          <strong>How to fix:</strong><br>
          1. Click the camera lock icon 🔒 next to the address bar.<br>
          2. Set Camera access to <strong>Allow</strong> and click <strong>Retry Camera</strong>.<br>
          3. Check Windows Privacy Settings → <em>Allow apps to access your camera</em>.
        `;
      }
    } else if (errName === 'NotFoundError' || errName === 'DevicesNotFoundError') {
      if (errorIcon) errorIcon.textContent = '📷❓';
      if (errorTitle) errorTitle.textContent = 'No Camera Detected';
      if (errorMessage) errorMessage.textContent = 'No webcam hardware was found connected to your computer.';
      if (errorDiagnosticHint) {
        errorDiagnosticHint.classList.remove('hidden');
        errorDiagnosticHint.innerHTML = `
          Plug in a USB webcam, or use <strong>Screen Share</strong> / <strong>Demo Monitor</strong> mode below to calibrate without a camera.
        `;
      }
    } else if (errName === 'NotReadableError' || errName === 'TrackStartError') {
      if (errorIcon) errorIcon.textContent = '📷🔒';
      if (errorTitle) errorTitle.textContent = 'Camera Already in Use';
      if (errorMessage) errorMessage.textContent = 'Your webcam is being used by another application (e.g. Zoom, Teams, Skype, or another browser tab).';
      if (errorDiagnosticHint) {
        errorDiagnosticHint.classList.remove('hidden');
        errorDiagnosticHint.innerHTML = `
          Close other video apps or browser tabs accessing your camera, then click <strong>Retry Camera</strong>.
        `;
      }
    } else {
      if (errorIcon) errorIcon.textContent = '📷❌';
      if (errorTitle) errorTitle.textContent = 'Camera Connection Error';
      if (errorMessage) errorMessage.textContent = (err && err.message) ? err.message : 'Could not initialize camera stream.';
      if (errorDiagnosticHint) {
        errorDiagnosticHint.classList.remove('hidden');
        errorDiagnosticHint.innerHTML = `
          Try selecting a different camera device from the dropdown above, or use <strong>Screen Share</strong> / <strong>Demo Monitor</strong>.
        `;
      }
    }
  }

  function hideError() {
    cameraError.classList.add('hidden');
  }

  // Live Monitoring & Backend Communication State
  let monitoringInterval = null;
  let isMonitoring = false;

  const startMonitoringBtn = document.getElementById('startMonitoringBtn');
  const stopMonitoringBtn = document.getElementById('stopMonitoringBtn');
  const monitoringSection = document.getElementById('monitoringSection');
  const monitoringStatusBadge = document.getElementById('monitoringStatusBadge');
  const monitoringStatusText = document.getElementById('monitoringStatusText');

  function showMonitoringSection() {
    if (monitoringSection) {
      monitoringSection.classList.remove('hidden');
    }
  }

  function updateMonitoringStatus(state, label) {
    if (monitoringStatusBadge) {
      monitoringStatusBadge.className = `status-badge status-${state}`;
    }
    if (monitoringStatusText) {
      monitoringStatusText.textContent = label;
    }
  }

  function startMonitoring() {
    if (isMonitoring) return;

    let savedStr = localStorage.getItem('monitorCalibration');
    if (!savedStr) {
      if (boxes && boxes.length > 0) {
        saveBtn.click();
        savedStr = localStorage.getItem('monitorCalibration');
      } else {
        const defaultCalib = getDefaultDemoCalibration();
        localStorage.setItem('monitorCalibration', JSON.stringify(defaultCalib));
        savedStr = JSON.stringify(defaultCalib);
      }
    }

    let calibration;
    try {
      calibration = JSON.parse(savedStr);
    } catch (e) {
      calibration = getDefaultDemoCalibration();
      localStorage.setItem('monitorCalibration', JSON.stringify(calibration));
    }

    if (!calibration.regions || !calibration.regions.heartRate) {
      calibration = getDefaultDemoCalibration();
      localStorage.setItem('monitorCalibration', JSON.stringify(calibration));
    }

    showMonitoringSection();
    isMonitoring = true;
    if (isFrozen) {
      unfreezeToLiveFeed();
    }
    if (startMonitoringBtn) startMonitoringBtn.classList.add('hidden');
    if (stopMonitoringBtn) stopMonitoringBtn.classList.remove('hidden');
    updateMonitoringStatus('live', 'Monitoring Active (1s real-time)');

    captureAndProcessReadings(calibration);
    monitoringInterval = setInterval(() => {
      captureAndProcessReadings(calibration);
    }, 1000);
  }

  function stopMonitoring() {
    if (!isMonitoring) return;
    isMonitoring = false;
    if (monitoringInterval) {
      clearInterval(monitoringInterval);
      monitoringInterval = null;
    }
    if (startMonitoringBtn) startMonitoringBtn.classList.remove('hidden');
    if (stopMonitoringBtn) stopMonitoringBtn.classList.add('hidden');
    updateMonitoringStatus('connecting', 'Monitoring Paused');
  }

  let isProcessingCycle = false;
  let sequentialFieldIndex = 0;
  const lastCycleResults = {};

  async function captureAndProcessReadings(calibration) {
    if (isProcessingCycle) return;
    isProcessingCycle = true;
    try {
      const width = (webcamFeed && webcamFeed.videoWidth) ? webcamFeed.videoWidth : (offscreenCanvas.width || calibration.frameWidth || TARGET_WIDTH);
      const height = (webcamFeed && webcamFeed.videoHeight) ? webcamFeed.videoHeight : (offscreenCanvas.height || calibration.frameHeight || TARGET_HEIGHT);

      const fullCanvas = document.createElement('canvas');
      fullCanvas.width = width;
      fullCanvas.height = height;
      const fullCtx = fullCanvas.getContext('2d');

      let drewFrame = false;

      if (webcamFeed && webcamFeed.videoWidth > 0 && !webcamFeed.paused && !webcamFeed.ended) {
        try {
          fullCtx.drawImage(webcamFeed, 0, 0, width, height);
          drewFrame = true;
        } catch (e) {}
      }

      if (!drewFrame && offscreenCanvas.width > 0 && offscreenCanvas.height > 0) {
        fullCtx.drawImage(offscreenCanvas, 0, 0, width, height);
        drewFrame = true;
      }

      if (!drewFrame) {
        console.warn('No active frame available for monitoring capture');
        return;
      }

      const scaleX = width / (calibration.frameWidth || width);
      const scaleY = height / (calibration.frameHeight || height);

      // ArUco Anchor Auto-Alignment Shift Computation
      let deltaX = 0;
      let deltaY = 0;
      let currentMarkerCount = 0;
      const autoAlignTextEl = document.getElementById('autoAlignText');
      const markerCountBadgeEl = document.getElementById('markerCountBadge');

      if (calibration.markers && Object.keys(calibration.markers).length > 0 && typeof ArUcoDetector !== 'undefined') {
        try {
          const detector = new ArUcoDetector();
          const frameImgData = fullCtx.getImageData(0, 0, width, height);
          const currentMarkers = detector.detect(frameImgData);
          currentMarkerCount = currentMarkers ? currentMarkers.length : 0;

          if (currentMarkers && currentMarkers.length > 0) {
            let sumDx = 0;
            let sumDy = 0;
            let matchCount = 0;

            currentMarkers.forEach(m => {
              const calibPos = calibration.markers[m.id];
              if (calibPos) {
                sumDx += (m.center.x - calibPos.x * scaleX);
                sumDy += (m.center.y - calibPos.y * scaleY);
                matchCount++;
              }
            });

            if (matchCount > 0) {
              deltaX = sumDx / matchCount;
              deltaY = sumDy / matchCount;
              window._lastKnownAlignment = { deltaX, deltaY };

              const shiftDist = Math.hypot(deltaX, deltaY);
              if (shiftDist > 3) {
                if (autoAlignTextEl) {
                  autoAlignTextEl.innerHTML = `<span style="color: #38bdf8;">🎯 Auto-Aligned (Camera Shift: ${deltaX > 0 ? '+' : ''}${Math.round(deltaX)}px, ${deltaY > 0 ? '+' : ''}${Math.round(deltaY)}px)</span>`;
                }
              } else {
                if (autoAlignTextEl) {
                  autoAlignTextEl.innerHTML = `<span style="color: #4ade80;">🎯 Anchor Locked (Aligned)</span>`;
                }
              }
            } else if (window._lastKnownAlignment) {
              deltaX = window._lastKnownAlignment.deltaX;
              deltaY = window._lastKnownAlignment.deltaY;
              if (autoAlignTextEl) {
                autoAlignTextEl.innerHTML = `<span style="color: #fbbf24;">⚠️ Anchor Occluded (Using Last Position)</span>`;
              }
            }
          } else if (window._lastKnownAlignment) {
            deltaX = window._lastKnownAlignment.deltaX;
            deltaY = window._lastKnownAlignment.deltaY;
            if (autoAlignTextEl) {
              autoAlignTextEl.innerHTML = `<span style="color: #fbbf24;">⚠️ Anchor Occluded (Using Last Position)</span>`;
            }
          } else {
            if (autoAlignTextEl) {
              autoAlignTextEl.innerHTML = `<span style="color: #94a3b8;">📍 Fixed ROI (Markers Not Visible)</span>`;
            }
          }
        } catch (err) {
          console.warn('Error computing ArUco alignment:', err);
        }
      } else {
        if (autoAlignTextEl) {
          autoAlignTextEl.innerHTML = `<span style="color: #94a3b8;">📍 Fixed ROI (No Markers Calibrated)</span>`;
        }
      }

      if (markerCountBadgeEl) {
        markerCountBadgeEl.textContent = `Markers: ${currentMarkerCount}`;
      }

      const fieldsMap = [
        { key: 'heartRate', fieldType: 'heart_rate' },
        { key: 'spo2', fieldType: 'spo2' },
        { key: 'bloodPressure', fieldType: 'blood_pressure' },
        { key: 'etco2', fieldType: 'etco2' }
      ];

      // Extract all 4 vital sign crops simultaneously in parallel for real-time 1s monitoring
      await Promise.all(fieldsMap.map(async ({ key, fieldType }) => {
        const region = calibration.regions[key];
        if (region && region.width > 0 && region.height > 0) {
          const rx = Math.max(0, Math.round((region.x * scaleX) + deltaX));
          const ry = Math.max(0, Math.round((region.y * scaleY) + deltaY));
          const rw = Math.min(width - rx, Math.round(region.width * scaleX));
          const rh = Math.min(height - ry, Math.round(region.height * scaleY));

          if (rw > 0 && rh > 0) {
            const cropCanvas = document.createElement('canvas');
            cropCanvas.width = rw;
            cropCanvas.height = rh;
            const cropCtx = cropCanvas.getContext('2d');

            cropCtx.drawImage(fullCanvas, rx, ry, rw, rh, 0, 0, rw, rh);

            const cropImgEl = document.getElementById(`crop-img-${fieldType}`);
            if (cropImgEl) {
              cropImgEl.src = cropCanvas.toDataURL('image/jpeg', 0.85);
            }

            await new Promise((resolve) => {
              cropCanvas.toBlob(async (blob) => {
                if (!blob) {
                  resolve();
                  return;
                }

                const formData = new FormData();
                formData.append('file', blob, `${fieldType}.jpg`);
                formData.append('field_type', fieldType);

                try {
                  const resp = await fetch(`${API_BASE}/read-value`, {
                    method: 'POST',
                    body: formData
                  });

                  if (resp.ok) {
                    const resData = await resp.json();
                    lastCycleResults[fieldType] = resData;
                    updateFieldUI(
                      fieldType,
                      resData.raw_value,
                      resData.smoothed_value,
                      resData.status
                    );
                  } else {
                    updateFieldUI(fieldType, null, null, 'error');
                  }
                } catch (err) {
                  console.error(`Failed sending ROI frame for ${fieldType}:`, err);
                  updateFieldUI(fieldType, null, null, 'error');
                }
                resolve();
              }, 'image/jpeg', 0.9);
            });
          }
        }
      }));

      const getVal = (fieldType) => (
        lastCycleResults[fieldType]?.status === 'ok' || lastCycleResults[fieldType]?.status === 'fallback_estimated'
          ? lastCycleResults[fieldType].smoothed_value
          : null
      );

      const hrVal = getVal('heart_rate');
      const spo2Val = getVal('spo2');
      const etco2Val = getVal('etco2');

      let bpSys = null;
      let bpDia = null;
      const bpVal = getVal('blood_pressure');
      if (typeof bpVal === 'string') {
        const match = bpVal.match(/^(\d+)\/(\d+)$/);
        if (match) {
          bpSys = parseFloat(match[1]);
          bpDia = parseFloat(match[2]);
        }
      }

      const cyclePayload = {
        heart_rate: hrVal,
        spo2: spo2Val,
        bp_systolic: bpSys,
        bp_diastolic: bpDia,
        etco2: etco2Val,
        readings: lastCycleResults
      };

      try {
        const cycleResp = await fetch(`${API_BASE}/process-cycle`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(cyclePayload)
        });

        if (cycleResp.ok) {
          const caseRes = await cycleResp.json();
          updateTopCaseStatus(caseRes.status, caseRes.case_id);

          const msg = caseRes.message || caseRes.status;
          const displayLabel = caseRes.case_id ? `${msg} (${caseRes.case_id})` : msg;
          
          if (caseRes.status === 'recording' || caseRes.status === 'case_started') {
            updateMonitoringStatus('live', displayLabel);
          } else if (caseRes.status === 'case_ended') {
            updateMonitoringStatus('frozen', displayLabel);
          } else {
            updateMonitoringStatus('connecting', displayLabel);
          }
        }
      } catch (err) {
        console.error('Failed to post cycle to /process-cycle:', err);
      }
    } catch (err) {
      console.error('Error during capture and process cycle:', err);
    } finally {
      isProcessingCycle = false;
    }
  }

  function updateTopCaseStatus(status, caseId) {
    const caseStatusBar = document.getElementById('caseStatusBar');
    const caseStatusIcon = document.getElementById('caseStatusIcon');
    const caseStatusText = document.getElementById('caseStatusText');
    const caseIdBadge = document.getElementById('caseIdBadge');
    const caseIdText = document.getElementById('caseIdText');
    const manualStartBtn = document.getElementById('manualStartCaseBtn');
    const manualEndBtn = document.getElementById('manualEndCaseBtn');

    if (!caseStatusBar) return;

    caseStatusBar.className = 'case-status-bar';

    if (status === 'case_started' || status === 'recording') {
      window._activeCaseId = caseId;
      caseStatusBar.classList.add('status-recording');
      if (caseStatusIcon) caseStatusIcon.textContent = '🟢';
      if (caseStatusText) caseStatusText.textContent = 'Case Started — Recording';
      if (manualStartBtn) manualStartBtn.disabled = true;
      if (manualEndBtn) manualEndBtn.disabled = false;
    } else if (status === 'case_ended') {
      window._activeCaseId = null;
      caseStatusBar.classList.add('status-ended');
      if (caseStatusIcon) caseStatusIcon.textContent = '🔴';
      if (caseStatusText) caseStatusText.textContent = 'Case Ended';
      if (manualStartBtn) manualStartBtn.disabled = false;
      if (manualEndBtn) manualEndBtn.disabled = true;
    } else if (status === 'camera_live' || status === 'live') {
      caseStatusBar.classList.add('status-live');
      if (caseStatusIcon) caseStatusIcon.textContent = '📷';
      if (caseStatusText) caseStatusText.textContent = 'Camera Signal Live — Freeze Frame & Draw Boxes to Calibrate';
      if (manualStartBtn) manualStartBtn.disabled = false;
      if (manualEndBtn) manualEndBtn.disabled = true;
    } else {
      caseStatusBar.classList.add('status-waiting');
      if (caseStatusIcon) caseStatusIcon.textContent = '⏳';
      if (caseStatusText) caseStatusText.textContent = 'Waiting for camera signal / calibration';
      if (manualStartBtn) manualStartBtn.disabled = false;
      if (manualEndBtn) manualEndBtn.disabled = true;
    }

    const dashboardLink = document.getElementById('dashboardLink');
    const cardDashboardBtn = document.getElementById('cardDashboardBtn');

    if (caseIdBadge && caseIdText) {
      if (caseId) {
        caseIdText.textContent = caseId;
        caseIdBadge.classList.remove('hidden');
        if (dashboardLink) {
          dashboardLink.href = `dashboard.html?case_id=${encodeURIComponent(caseId)}`;
        }
        if (cardDashboardBtn) {
          cardDashboardBtn.href = `dashboard.html?case_id=${encodeURIComponent(caseId)}`;
          cardDashboardBtn.classList.remove('hidden');
        }
      } else {
        caseIdBadge.classList.add('hidden');
        if (cardDashboardBtn) {
          cardDashboardBtn.classList.add('hidden');
        }
      }
    }
  }

  function updateFieldUI(fieldType, rawValue, smoothedValue, status) {
    const smoothedEl = document.getElementById(`smoothed-${fieldType}`);
    const rawEl = document.getElementById(`raw-${fieldType}`);
    const dotEl = document.getElementById(`dot-${fieldType}`);
    const statusEl = document.getElementById(`status-${fieldType}`);
    const noteEl = document.getElementById(`note-${fieldType}`);

    if (smoothedEl) {
      smoothedEl.textContent = smoothedValue !== null && smoothedValue !== undefined ? smoothedValue : '--';
    }
    if (rawEl) {
      rawEl.textContent = rawValue !== null && rawValue !== undefined ? rawValue : '--';
    }

    if (statusEl) {
      if (status === 'ok') {
        if (dotEl) { dotEl.style.backgroundColor = '#34D399'; dotEl.style.boxShadow = '0 0 6px #34D399'; }
        statusEl.textContent = 'ok';
        statusEl.style.color = '#34D399';
        if (noteEl) noteEl.classList.add('hidden');
      } else if (status === 'fallback_estimated') {
        if (dotEl) { dotEl.style.backgroundColor = '#C084FC'; dotEl.style.boxShadow = '0 0 6px #C084FC'; }
        statusEl.textContent = 'Demo simulation';
        statusEl.style.color = '#C084FC';
        if (noteEl) noteEl.classList.add('hidden');
      } else if (status === 'bad_frame') {
        if (dotEl) { dotEl.style.backgroundColor = '#FB923C'; dotEl.style.boxShadow = 'none'; }
        statusEl.textContent = 'bad frame';
        statusEl.style.color = '#FB923C';
        if (noteEl) noteEl.classList.remove('hidden');
      } else if (status === 'signal_lost') {
        if (dotEl) { dotEl.style.backgroundColor = '#FB923C'; dotEl.style.boxShadow = 'none'; }
        statusEl.textContent = 'signal lost';
        statusEl.style.color = '#FB923C';
        if (noteEl) noteEl.classList.remove('hidden');
      } else if (status === 'unreadable') {
        if (dotEl) { dotEl.style.backgroundColor = '#94A3B8'; dotEl.style.boxShadow = 'none'; }
        statusEl.textContent = 'unreadable';
        statusEl.style.color = '#94A3B8';
        if (noteEl) noteEl.classList.remove('hidden');
      } else if (status === 'invalid_range') {
        if (dotEl) { dotEl.style.backgroundColor = '#F87171'; dotEl.style.boxShadow = 'none'; }
        statusEl.textContent = 'invalid range';
        statusEl.style.color = '#F87171';
        if (noteEl) noteEl.classList.remove('hidden');
        console.warn(`[Digitizer Warning] Invalid range for ${fieldType}: raw=${rawValue}, holding last smoothed=${smoothedValue}`);
      } else {
        if (dotEl) { dotEl.style.backgroundColor = '#F87171'; dotEl.style.boxShadow = 'none'; }
        statusEl.textContent = 'error';
        statusEl.style.color = '#F87171';
        if (noteEl) noteEl.classList.remove('hidden');
        console.warn(`[Digitizer Error] Processing error for ${fieldType}: status=${status}, holding last smoothed=${smoothedValue}`);
      }
    }
  }

  // Check for existing saved calibration in localStorage
  function checkSavedCalibration() {
    try {
      const savedStr = localStorage.getItem('monitorCalibration');
      if (savedStr) {
        const savedData = JSON.parse(savedStr);
        if (savedData && savedData.regions) {
          console.log('Saved monitor calibration found in localStorage:', savedData);
        }
      }
    } catch (e) {
      console.warn('Could not read existing calibration:', e);
    }
  }

  async function checkInitialActiveCase() {
    try {
      const resp = await fetch(`${API_BASE}/active-case`);
      if (resp.ok) {
        const data = await resp.json();
        if (data.case_id) {
          updateTopCaseStatus('recording', data.case_id);
        } else {
          updateTopCaseStatus('waiting', null);
        }
      }
    } catch (err) {
      console.warn('Could not check initial active case state:', err);
    }
  }

  // Event Listeners
  freezeBtn.addEventListener('click', toggleFreezeFrame);
  retakeBtn.addEventListener('click', retakeFrame);
  if (retryCameraBtn) {
    retryCameraBtn.addEventListener('click', () => initCamera());
  }
  if (cameraSelect) {
    cameraSelect.addEventListener('change', (e) => {
      initCamera(e.target.value);
    });
  }
  if (screenShareBtn) screenShareBtn.addEventListener('click', initScreenShare);
  if (simulatedFeedBtn) simulatedFeedBtn.addEventListener('click', initSimulatedFeed);
  if (errorScreenShareBtn) errorScreenShareBtn.addEventListener('click', initScreenShare);
  if (errorSimulatedBtn) errorSimulatedBtn.addEventListener('click', initSimulatedFeed);

  if (startMonitoringBtn) {
    startMonitoringBtn.addEventListener('click', startMonitoring);
  }
  if (stopMonitoringBtn) {
    stopMonitoringBtn.addEventListener('click', stopMonitoring);
  }

  const manualStartBtn = document.getElementById('manualStartCaseBtn');
  const manualEndBtn = document.getElementById('manualEndCaseBtn');
  const saveCaseMetaBtn = document.getElementById('saveCaseMetaBtn');

  async function sendCaseStartWithMetadata() {
    const pId = document.getElementById('patientIdInput')?.value.trim() || null;
    const aId = document.getElementById('anesthetistIdInput')?.value.trim() || null;
    const room = document.getElementById('orRoomInput')?.value.trim() || null;

    try {
      const resp = await fetch(`${API_BASE}/case/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          patient_id: pId,
          anesthetist_id: aId,
          or_room: room
        })
      });
      if (resp.ok) {
        const resData = await resp.json();
        updateTopCaseStatus(resData.status, resData.case_id);
        return resData;
      }
    } catch (err) {
      console.error('Failed to start/update case metadata:', err);
    }
    return null;
  }

  if (saveCaseMetaBtn) {
    saveCaseMetaBtn.addEventListener('click', async () => {
      const res = await sendCaseStartWithMetadata();
      if (res && saveCaseMetaBtn) {
        const origText = saveCaseMetaBtn.textContent;
        saveCaseMetaBtn.textContent = '✅ Saved!';
        saveCaseMetaBtn.style.backgroundColor = '#10b981';
        setTimeout(() => {
          saveCaseMetaBtn.textContent = origText;
          saveCaseMetaBtn.style.backgroundColor = '';
        }, 2000);
      }
    });
  }

  if (manualStartBtn) {
    manualStartBtn.addEventListener('click', async () => {
      await sendCaseStartWithMetadata();
    });
  }

  if (manualEndBtn) {
    manualEndBtn.addEventListener('click', async () => {
      try {
        const resp = await fetch(`${API_BASE}/case/end`, {
          method: 'POST'
        });
        if (resp.ok) {
          const resData = await resp.json();
          updateTopCaseStatus(resData.status, resData.case_id);
        }
      } catch (err) {
        console.error('Failed to manually end case:', err);
      }
    });
  }

  // Network LAN URL & QR Code Modal Logic (Points to Live Clinical Dashboard for Mobile / iPad)
  let currentLanUrl = `${API_BASE}/app/dashboard.html`;
  let qrCodeInstance = null;

  async function initNetworkInfo() {
    const lanUrlDisplay = document.getElementById('lanUrlDisplay');
    const qrcodeContainer = document.getElementById('qrcodeContainer');

    try {
      const resp = await fetch(`${API_BASE}/network-info`);
      if (resp.ok) {
        const data = await resp.json();
        currentLanUrl = data.lan_url || `${API_BASE}/app/dashboard.html`;
      }
    } catch (e) {
      console.warn('Could not fetch network info:', e);
      currentLanUrl = `${API_BASE}/app/dashboard.html`;
    }

    if (lanUrlDisplay) {
      lanUrlDisplay.textContent = currentLanUrl;
    }

    if (qrcodeContainer && window.QRCode) {
      qrcodeContainer.innerHTML = '';
      try {
        qrCodeInstance = new QRCode(qrcodeContainer, {
          text: currentLanUrl,
          width: 160,
          height: 160,
          colorDark: '#0f172a',
          colorLight: '#ffffff',
          correctLevel: QRCode.CorrectLevel.M
        });
      } catch (err) {
        console.warn('Could not generate QR code:', err);
      }
    }
  }

  const qrModalOpenBtn = document.getElementById('qrModalOpenBtn');
  const closeQrModalBtn = document.getElementById('closeQrModalBtn');
  const copyLanUrlBtn = document.getElementById('copyLanUrlBtn');
  const qrCodeModal = document.getElementById('qrCodeModal');

  if (qrModalOpenBtn && qrCodeModal) {
    qrModalOpenBtn.addEventListener('click', () => {
      qrCodeModal.classList.remove('hidden');
    });
  }

  if (closeQrModalBtn && qrCodeModal) {
    closeQrModalBtn.addEventListener('click', () => {
      qrCodeModal.classList.add('hidden');
    });
  }

  if (copyLanUrlBtn) {
    copyLanUrlBtn.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(currentLanUrl);
        const originalText = copyLanUrlBtn.textContent;
        copyLanUrlBtn.textContent = '✅ Copied!';
        setTimeout(() => {
          copyLanUrlBtn.textContent = originalText;
        }, 2000);
      } catch (err) {
        console.warn('Clipboard copy failed:', err);
      }
    });
  }

  // Initialize Application
  populateCameraDevices();
  initCamera();
  checkSavedCalibration();
  checkInitialActiveCase();
  initNetworkInfo();
});
