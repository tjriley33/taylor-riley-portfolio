// ============================================
// Taylor Riley — Portfolio JavaScript
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    initNav();
    initParticles();
    initCounters();
    initRevealAnimations();
    initSmoothScroll();
    initBlogProgress();
    initTaxCompiler();
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

// --- Blog Reading Progress ---
function initBlogProgress() {
    const cards = document.querySelectorAll('.blog-card');
    if (!cards.length) return;

    function updateProgress() {
        cards.forEach(card => {
            const bar = card.querySelector('.blog-progress-bar');
            const body = card.querySelector('.blog-body');
            if (!bar || !body) return;

            if (!card.classList.contains('expanded')) {
                bar.style.width = '0%';
                return;
            }

            const rect = body.getBoundingClientRect();
            const bodyHeight = body.offsetHeight;
            const viewportHeight = window.innerHeight;
            const scrolled = -rect.top;
            const total = bodyHeight - viewportHeight;
            const progress = Math.max(0, Math.min(100, (scrolled / total) * 100));
            bar.style.width = progress + '%';
        });
    }

    window.addEventListener('scroll', updateProgress, { passive: true });
    window.addEventListener('resize', updateProgress);

    document.querySelectorAll('.blog-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            requestAnimationFrame(updateProgress);
        });
    });
}

// --- Tax Compiler Terminal Simulation ---
function initTaxCompiler() {
    const terminal = document.getElementById('tax-compiler-terminal');
    if (!terminal) return;

    const screen = document.getElementById('terminal-screen');
    const btnCompile = document.getElementById('btn-compile');
    const btnPatch = document.getElementById('btn-patch');
    const btnClear = document.getElementById('btn-clear');

    const defaultLines = [
        '<div class="terminal-line"><span class="prompt">$</span> taxc --compile --optimize -f form1040.xml</div>',
        '<div class="terminal-line info">[INFO] Initializing IRC parser engine...</div>',
        '<div class="terminal-line info">[INFO] Loaded 74,000 pages of logic guidelines.</div>',
        '<div class="terminal-line warn">[WARN] Sec. 163(h): Deprecated mortgage interest deduction contains obsolete logic gates.</div>',
        '<div class="terminal-line warn">[WARN] Sec. 199A: Qualified Business Income calculation pattern is highly unstable.</div>',
        '<div class="terminal-line error">[ERR] Compilation failed: Circular dependency detected in state_federal_loop.o.</div>',
        '<div class="terminal-line error">[ERR] Stack overflow. Please run manual iterative reconciliation or hire a CPA.</div>'
    ];

    const patchLines = [
        '<div class="terminal-line"><span class="prompt">$</span> taxc --apply-patch omnibus_bill_2026.patch</div>',
        '<div class="terminal-line info">[INFO] Applying Congress Omnibus patch...</div>',
        '<div class="terminal-line info">[INFO] Injecting 4,500 new conditional clauses into Section 179.</div>',
        '<div class="terminal-line info">[INFO] Rewriting phase-out schedules for 12 tax brackets.</div>',
        '<div class="terminal-line warn">[WARN] Registry conflict: 43 state tax schemas failed validation.</div>',
        '<div class="terminal-line info">[INFO] Executing regression unit tests...</div>',
        '<div class="terminal-line error">[ERR] AssertFailed: taxpayer.sanity == true (Actual: false)</div>',
        '<div class="terminal-line error">[ERR] Compilation aborted: 14,082 warnings, 1 error. Build failed.</div>'
    ];

    let typingTimeout;

    function clearScreen() {
        clearTimeout(typingTimeout);
        screen.innerHTML = '';
    }

    function typeLines(linesArray, index = 0) {
        if (index >= linesArray.length) return;

        const lineEl = document.createElement('div');
        lineEl.innerHTML = linesArray[index];
        const actualLine = lineEl.firstElementChild;
        actualLine.style.opacity = '0';
        actualLine.style.animation = 'fadeInLine 0.15s forwards';
        screen.appendChild(actualLine);

        screen.scrollTop = screen.scrollHeight;

        typingTimeout = setTimeout(() => {
            typeLines(linesArray, index + 1);
        }, 300);
    }

    btnCompile.addEventListener('click', () => {
        clearScreen();
        typeLines(defaultLines);
    });

    btnPatch.addEventListener('click', () => {
        clearScreen();
        typeLines(patchLines);
    });

    btnClear.addEventListener('click', () => {
        clearScreen();
        const cursorLine = document.createElement('div');
        cursorLine.className = 'terminal-line';
        cursorLine.innerHTML = '<span class="prompt">$</span> <span class="blink">_</span>';
        screen.appendChild(cursorLine);
    });
}
