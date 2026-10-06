"use strict";
Object.defineProperty(exports, "__esModule", {
    value: true
});
Object.defineProperty(exports, "getRootDirs", {
    enumerable: true,
    get: function() {
        return getRootDirs;
    }
});
var _glob = require("glob");
var _fs = require("node:fs");
var _path = require("node:path");
var _braceExpansion = require("brace-expansion");
var _picomatch = require("picomatch");
/**
 * Process a Next.js root directory glob.
 */ var processRootDir = function(rootDir) {
    var pattern = rootDir.replace(/\\/g, '/');
    // Bound parser nesting before passing config input to any glob library.
    var depth = 0;
    for (var character of pattern) {
        if (character === '{' && ++depth > 100) {
            throw new SyntaxError('Next rootDir brace depth exceeds 100');
        }
        if (character === '}') depth = Math.max(0, depth - 1);
    }
    // fast-glob expands braces before separating positive/negative patterns.
    var expanded = (0, _braceExpansion.expand)(pattern);
    var isNegative = function(value) { return value[0] === '!' && value[1] !== '('; };
    var positive = expanded.filter(function(value) { return !isNegative(value); });
    if (positive.length === 0) return [];
    var normalize = function(value) {
        return value.replace(/^(\.\/)+/, '').replace(/([^/])\/{2,}/g, '$1/')
            .replace(/\/(?:\.\/)+/g, '/').replace(/\/$/, '') || '.';
    };
    var negative = expanded.filter(isNegative).flatMap(function(value) {
        var excluded = normalize(value.slice(1));
        return [excluded, excluded + '/**'];
    });
    var anchor = function(value) {
        var scanned = _picomatch.scan(normalize(value));
        return _path.resolve(scanned.base) + (scanned.glob ? '/' + scanned.glob : '');
    };
    var matches = _picomatch(positive.map(anchor), { dot: false });
    var ignores = _picomatch(negative, { dot: true });
    // A terminal globstar in fast-glob matches descendants, not its base.
    var isDirectory = function(directory) {
        return _fs.statSync(directory, { throwIfNoEntry: false })?.isDirectory();
    };
    // Preserve literal dot/parent segments (and symlink identity) as upstream does.
    var literal = positive.filter(function(value) { return !_glob.hasMagic(value); }).filter(isDirectory);
    var discovery = positive.filter(function(value) { return _glob.hasMagic(value); }).map(function(value) {
        return value === '**' || value.endsWith('/**') ? value + '/*' : value;
    });
    var discovered = (0, _glob.globSync)(discovery, {
        follow: true,
        nocase: false,
        dot: true,
        ignore: negative
    }).filter(function(directory) {
        // glob already matched ordinary paths. Only reconcile hidden-directory
        // semantics here; re-matching canonical paths would lose ../ segments.
        var hidden = normalize(directory).split('/').some(function(part) {
            return part[0] === '.' && part !== '.' && part !== '..';
        });
        return (!hidden || matches(_path.resolve(directory))) && isDirectory(directory);
    });
    return Array.from(new Set(literal.concat(discovered))).filter(function(directory) {
        return !ignores(normalize(directory));
    });
};
var getRootDirs = function(context) {
    var rootDirs = [
        context.cwd
    ];
    var nextSettings = context.settings.next || {};
    var rootDir = nextSettings.rootDir;
    if (typeof rootDir === 'string') {
        rootDirs = processRootDir(rootDir);
    } else if (Array.isArray(rootDir)) {
        rootDirs = rootDir.map(function(dir) {
            return typeof dir === 'string' ? processRootDir(dir) : [];
        }).flat();
    }
    return rootDirs;
};
