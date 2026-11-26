document.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) window.lucide.createIcons();

  const themeToggle = document.querySelector(".theme-toggle");
  if (themeToggle) {
    const themeIcon = themeToggle.querySelector(".theme-toggle-icon");
    let darkTheme = document.body.classList.contains("dark");
    try {
      const savedTheme = window.localStorage.getItem("tuition-theme");
      if (savedTheme === "light") darkTheme = false;
      if (savedTheme === "dark") darkTheme = true;
    } catch (error) {
      console.warn("Theme preference could not be loaded.", error);
    }

    const applyTheme = value => {
      darkTheme = value;
      document.body.classList.toggle("dark", darkTheme);
      themeToggle.setAttribute("aria-pressed", String(darkTheme));
      themeToggle.setAttribute("aria-label", `Switch to ${darkTheme ? "light" : "dark"} theme`);
      themeToggle.querySelector("[data-theme-label]").textContent = `${darkTheme ? "Light" : "Dark"} theme`;
      themeIcon.replaceChildren();
      const icon = document.createElement("i");
      icon.setAttribute("data-lucide", darkTheme ? "sun" : "moon");
      icon.setAttribute("aria-hidden", "true");
      themeIcon.appendChild(icon);
      if (window.lucide) window.lucide.createIcons();
      try {
        window.localStorage.setItem("tuition-theme", darkTheme ? "dark" : "light");
      } catch (error) {
        console.warn("Theme preference could not be saved.", error);
      }
    };

    applyTheme(darkTheme);
    themeToggle.addEventListener("click", () => applyTheme(!darkTheme));
  }

  const navToggle = document.querySelector(".nav-toggle");
  const navLinks = document.querySelector(".nav-links");
  if (navToggle && navLinks) {
    navToggle.addEventListener("click", () => {
      const open = navLinks.classList.toggle("open");
      navToggle.setAttribute("aria-expanded", String(open));
      navToggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    });
  }

  document.querySelectorAll(".password-toggle").forEach(button => {
    button.addEventListener("click", () => {
      const field = button.closest(".password-field")?.querySelector("input");
      if (!field) return;
      field.type = field.type === "password" ? "text" : "password";
      const visible = field.type === "text";
      button.setAttribute("aria-pressed", String(visible));
      button.setAttribute("aria-label", visible ? "Hide password" : "Show password");
    });
  });

  const password = document.querySelector("#register-password");
  const confirm = document.querySelector("#register-confirm");
  const strength = document.querySelector("#strength");
  const match = document.querySelector("#password-match");
  if (password) {
    const updatePassword = () => {
      const value = password.value;
      let score = 0;
      if (value.length >= 8) score++;
      if (/[A-Z]/.test(value) && /[a-z]/.test(value)) score++;
      if (/\d/.test(value)) score++;
      if (/[^A-Za-z0-9]/.test(value)) score++;
      const labels = ["Very weak", "Weak", "Fair", "Good", "Strong"];
      if (strength) {
        strength.textContent = value ? `Password strength: ${labels[score]}` : "";
        strength.dataset.score = String(score);
      }
      if (match && confirm) {
        match.textContent = confirm.value
          ? (value === confirm.value ? "Passwords match." : "Passwords do not match.")
          : "";
      }
    };
    password.addEventListener("input", updatePassword);
    confirm?.addEventListener("input", updatePassword);
  }

  document.querySelectorAll(".dashboard-menu").forEach(button => {
    button.addEventListener("click", () => {
      const target = document.querySelector(`#${button.getAttribute("aria-controls")}`);
      if (!target) return;
      const open = target.classList.toggle("open");
      button.setAttribute("aria-expanded", String(open));
    });
  });

  const observerSupported = "IntersectionObserver" in window;
  if (observerSupported && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add("visible");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    document.querySelectorAll(".reveal").forEach(el => observer.observe(el));
  } else {
    document.querySelectorAll(".reveal").forEach(el => el.classList.add("visible"));
  }

  document.querySelectorAll("[data-count]").forEach(el => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.textContent = Number(el.dataset.count || 0).toLocaleString();
      return;
    }
    const target = Number(el.dataset.count || 0);
    let current = 0;
    const step = Math.max(1, Math.ceil(target / 40));
    const timer = window.setInterval(() => {
      current = Math.min(target, current + step);
      el.textContent = current.toLocaleString();
      if (current >= target) window.clearInterval(timer);
    }, 25);
  });

  document.querySelectorAll(".toast").forEach(toast => {
    window.setTimeout(() => toast.remove(), 4500);
  });
});
