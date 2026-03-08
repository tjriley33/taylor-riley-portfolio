// ============================================
// Taylor Riley — Portfolio JavaScript
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    initNav();
    initParticles();
    initCounters();
    initRevealAnimations();
    initSmoothScroll();
});

// --- Navigation ---
function initNav() {
    const nav = document.getElementById('nav');
    const toggle = document.getElementById('nav-toggle');
    const links = document.getElementById('nav-links');

    // Scroll effect
    let lastScroll = 0;
    window.addEventListener('scroll', () => {
        const scrollY = window.scrollY;
        nav.classList.toggle('scrolled', scrollY > 50);
        lastScroll = scrollY;
    });

    // Mobile toggle
    const overlay = document.getElementById('nav-overlay');

    function closeMenu() {
        links.classList.remove('open');
        toggle.classList.remove('active');
        overlay.classList.remove('visible');
        document.body.style.overflow = '';
    }

    function openMenu() {
        links.classList.add('open');
        toggle.classList.add('active');
        overlay.classList.add('visible');
        document.body.style.overflow = 'hidden';
    }

    toggle.addEventListener('click', () => {
        if (links.classList.contains('open')) {
            closeMenu();
        } else {
            openMenu();
        }
    });

    overlay.addEventListener('click', closeMenu);

    // Close mobile menu on link click
    links.querySelectorAll('a').forEach(link => {
        link.addEventListener('click', closeMenu);
    });
}

// --- Particles ---
function initParticles() {
    const container = document.getElementById('particles');
    if (!container) return;

    const count = 30;
    for (let i = 0; i < count; i++) {
        const particle = document.createElement('div');
        particle.className = 'particle';
        particle.style.left = Math.random() * 100 + '%';
        particle.style.top = 50 + Math.random() * 50 + '%';
        particle.style.animationDelay = Math.random() * 8 + 's';
        particle.style.animationDuration = 6 + Math.random() * 6 + 's';
        const size = 2 + Math.random() * 3;
        particle.style.width = size + 'px';
        particle.style.height = size + 'px';
        container.appendChild(particle);
    }
}

// --- Animated Counters ---
function initCounters() {
    const counters = document.querySelectorAll('.stat-number[data-target]');
    let animated = false;

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting && !animated) {
                animated = true;
                counters.forEach(counter => animateCounter(counter));
            }
        });
    }, { threshold: 0.5 });

    counters.forEach(counter => observer.observe(counter));
}

function animateCounter(el) {
    const target = parseInt(el.dataset.target);
    const duration = 2000;
    const start = performance.now();

    function update(now) {
        const elapsed = now - start;
        const progress = Math.min(elapsed / duration, 1);
        // Ease out cubic
        const eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(eased * target);

        if (progress < 1) {
            requestAnimationFrame(update);
        }
    }

    requestAnimationFrame(update);
}

// --- Reveal on Scroll ---
function initRevealAnimations() {
    const reveals = [
        '.about-grid',
        '.timeline-item',
        '.project-card',
        '.skill-category',
        '.testimonial-card',
        '.lf-card',
        '.education-card',
        '.contact-wrapper'
    ];

    reveals.forEach(selector => {
        document.querySelectorAll(selector).forEach(el => {
            el.classList.add('reveal');
        });
    });

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
            }
        });
    }, {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    });

    document.querySelectorAll('.reveal').forEach(el => observer.observe(el));
}

// --- Smooth Scroll ---
function initSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                const offset = 80;
                const top = target.getBoundingClientRect().top + window.scrollY - offset;
                window.scrollTo({ top, behavior: 'smooth' });
            }
        });
    });
}
