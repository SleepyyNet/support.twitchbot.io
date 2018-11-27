function toggleNav(n) {
    if ($(n).is(':visible')) {
        $(n).css('display', 'none');
    } else {
        $(n).css('display', 'block');
    }
}

function resizeCtx() {
    var pos = $("#nav-toggle").position();
    $("#nav-ctx").css('top', `${pos.top + $('#nav-toggle').height() + 10}px`);
    $("#nav-ctx").css('left', `${pos.left + $('#nav-toggle').height() - 90}px`);
}

window.onresize = resizeCtx;
resizeCtx();
