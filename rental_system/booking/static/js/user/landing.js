document.addEventListener("DOMContentLoaded", function () {
    const hamburger = document.getElementById("hamburger");
    const navLinks = document.querySelector(".nav-links");

    if (hamburger && navLinks) {
        hamburger.addEventListener("click", function () {
            hamburger.classList.toggle("open");
            navLinks.classList.toggle("open");

            const isOpen = navLinks.classList.contains("open");
            hamburger.setAttribute("aria-expanded", isOpen);
        });

        navLinks.querySelectorAll("a").forEach(function (link) {
            link.addEventListener("click", function () {
                hamburger.classList.remove("open");
                navLinks.classList.remove("open");
                hamburger.setAttribute("aria-expanded", false);
            });
        });

        document.addEventListener("click", function (e) {
            const nav = document.querySelector("nav");
            if (nav && !nav.contains(e.target)) {
                hamburger.classList.remove("open");
                navLinks.classList.remove("open");
                hamburger.setAttribute("aria-expanded", false);
            }
        });

        window.addEventListener("resize", function () {
            if (window.innerWidth > 768) {
                hamburger.classList.remove("open");
                navLinks.classList.remove("open");
                hamburger.setAttribute("aria-expanded", false);
            }
        });
    }

});