(() => {
  const form = document.getElementById("upload-form");
  const input = document.getElementById("file");
  const label = document.getElementById("drop-label");
  if (!form || !input || !label) return;

  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    label.textContent = file ? file.name : "Выбрать PDF или бросить сюда";
  });

  form.addEventListener("dragover", (ev) => ev.preventDefault());
  form.addEventListener("drop", (ev) => {
    ev.preventDefault();
    const file = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
    if (!file) return;
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    label.textContent = file.name;
  });
})();
