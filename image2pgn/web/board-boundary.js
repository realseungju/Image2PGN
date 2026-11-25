(function () {
  const messages = {
    en: {
      title: "Confirm the board boundary",
      options: "Choose the complete board to analyze.",
      incomplete: "The main board is cut off. Upload a complete screenshot of it or choose another visible board.",
      recapture: "Upload a screenshot with all eight rows and columns visible.",
      manual: "Mark four corners",
      instruction: "Click the visible corners in order: top left, top right, bottom right, bottom left.",
      confirm: "Use these corners",
      replace: "Upload a new screenshot",
      choice: "Use board",
      imageError: "The original screenshot could not be shown.",
    },
    ko: {
      title: "체스판 테두리 확인",
      options: "분석할 체스판을 고르세요.",
      incomplete: "메인 체스판이 잘렸습니다. 메인 체스판이 전부 보이는 화면을 첨부하거나 다른 체스판을 고르세요.",
      recapture: "8행과 8열이 모두 보이는 화면을 첨부하세요.",
      manual: "네 모서리 직접 지정",
      instruction: "보이는 모서리를 왼쪽 위, 오른쪽 위, 오른쪽 아래, 왼쪽 아래 순서로 누르세요.",
      confirm: "이 테두리 사용",
      replace: "새 화면 첨부",
      choice: "체스판 선택",
      imageError: "원본 화면을 표시할 수 없습니다.",
    },
  };

  function render(container, review) {
    container.replaceChildren();
    container.hidden = !review;
    if (!review) return;

    const { details, source, onCorners, onImage, lang } = review;
    const text = messages[lang];
    const options = details.review_options || [];
    const image = new Image();
    const canvas = document.createElement("canvas");
    canvas.hidden = true;
    canvas.setAttribute("aria-label", text.instruction);
    const title = document.createElement("h2");
    title.textContent = text.title;
    const description = document.createElement("p");
    description.textContent = options.length ? text.options : text.recapture;
    if (options.length && details.selection_reason === "incomplete_grid") {
      description.textContent = text.incomplete;
    }
    const controls = document.createElement("div");
    controls.className = "boundary-actions";
    const status = document.createElement("p");
    status.setAttribute("role", "status");
    container.append(title, description, canvas, controls, status);

    let points = null;
    let busy = false;
    let imageLoaded = false;
    const current = () => container.contains(canvas);
    function button(label, action) {
      const element = document.createElement("button");
      element.type = "button";
      element.textContent = label;
      element.onclick = action;
      controls.append(element);
      return element;
    }
    function refreshControls() {
      for (const option of choices) option.disabled = busy || !imageLoaded;
      manual.disabled = busy;
      confirm.disabled = busy || points?.length !== 4;
      fileInput.disabled = busy;
    }
    async function submit(action) {
      if (busy || !current()) return;
      busy = true;
      status.textContent = "";
      refreshControls();
      try {
        await action();
      } catch (error) {
        status.textContent = error.message;
      } finally {
        busy = false;
        if (current()) refreshControls();
      }
    }
    const choices = options.map(([x, y, width, height], index) => {
      const right = x + width - 1;
      const bottom = y + height - 1;
      return button(`${text.choice} ${index + 1}`, () => submit(() => onCorners([
        [x, y], [right, y], [right, bottom], [x, bottom],
      ])));
    });
    const manual = button(text.manual, () => {
      points = [];
      description.textContent = text.instruction;
      confirm.hidden = false;
      confirm.disabled = true;
      draw();
    });
    manual.hidden = true;
    const confirm = button(text.confirm, () => submit(() => onCorners(points)));
    confirm.hidden = true;

    const replacement = document.createElement("label");
    replacement.textContent = text.replace + " ";
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = "image/png,image/jpeg";
    fileInput.onchange = () => {
      const file = fileInput.files[0];
      fileInput.value = "";
      if (file) void submit(() => onImage(file));
    };
    replacement.append(fileInput);
    controls.append(replacement);
    refreshControls();

    function draw() {
      const ctx = canvas.getContext("2d");
      const sx = canvas.width / image.naturalWidth;
      const sy = canvas.height / image.naturalHeight;
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      ctx.strokeStyle = "#23dda2";
      ctx.fillStyle = "#23dda2";
      ctx.font = "bold 20px sans-serif";
      ctx.lineWidth = 3;
      if (points) {
        ctx.beginPath();
        points.forEach(([x, y], index) => {
          if (index === 0) ctx.moveTo(x * sx, y * sy);
          else ctx.lineTo(x * sx, y * sy);
        });
        if (points.length === 4) ctx.closePath();
        ctx.stroke();
        points.forEach(([x, y], index) => ctx.fillText(String(index + 1), x * sx + 4, y * sy + 21));
        return;
      }
      options.forEach(([x, y, width, height], index) => {
        ctx.strokeRect(x * sx, y * sy, width * sx, height * sy);
        ctx.fillText(String(index + 1), x * sx + 6, y * sy + 23);
      });
    }
    canvas.onclick = (event) => {
      if (!points || points.length === 4 || busy) return;
      const view = canvas.getBoundingClientRect();
      const x = (event.clientX - view.left) / view.width;
      const y = (event.clientY - view.top) / view.height;
      points.push([Math.round(x * (image.naturalWidth - 1)), Math.round(y * (image.naturalHeight - 1))]);
      confirm.disabled = points.length !== 4;
      draw();
    };
    void (async () => {
      let objectUrl;
      try {
        const value = await source();
        if (!current()) return;
        image.src = value instanceof Blob ? (objectUrl = URL.createObjectURL(value)) : value;
        await image.decode();
        if (!current()) return;
        const scale = Math.min(1, 1200 / Math.max(image.naturalWidth, image.naturalHeight));
        canvas.width = Math.max(1, Math.round(scale * image.naturalWidth));
        canvas.height = Math.max(1, Math.round(scale * image.naturalHeight));
        canvas.hidden = false;
        manual.hidden = false;
        draw();
        imageLoaded = true;
        refreshControls();
      } catch {
        if (current()) status.textContent = text.imageError;
      } finally {
        if (objectUrl) URL.revokeObjectURL(objectUrl);
      }
    })();
  }

  window.ChessLensBoundary = { render };
})();
