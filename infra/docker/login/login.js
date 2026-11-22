const form = document.querySelector("form");
const error = document.getElementById("error");
const button = form.querySelector("button");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (button.disabled) return;
  error.textContent = "";
  button.disabled = true;
  button.textContent = "Входим…";
  try {
    const response = await fetch(form.action, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    if (response.status === 204) {
      form.reset();
      location.replace("/dev/" + (location.hash === "#evaluations" ? location.hash : ""));
      return;
    }
    if (response.status === 401) {
      error.textContent = "Неверный логин или пароль.";
      form.elements.password.select();
    } else if (response.status === 429) {
      error.textContent = "Попробуйте войти ещё раз через несколько секунд.";
    } else {
      error.textContent = "Не удалось войти. Попробуйте ещё раз.";
    }
  } catch {
    error.textContent = "Проверьте подключение и попробуйте ещё раз.";
  } finally {
    button.disabled = false;
    button.textContent = "Войти";
  }
});
