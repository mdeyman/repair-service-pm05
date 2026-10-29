let currentSlide = 0;

function showSlide() {
    const slides = document.querySelectorAll(".slide");

    if (slides.length === 0) {
        return;
    }

    slides.forEach(slide => slide.classList.remove("active"));
    slides[currentSlide].classList.add("active");

    currentSlide = (currentSlide + 1) % slides.length;
}

setInterval(showSlide, 3000);
showSlide();
