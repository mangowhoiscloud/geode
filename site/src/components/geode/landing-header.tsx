"use client";

import Link from "next/link";
import { useRef } from "react";
import { Menu } from "lucide-react";
import { GeodiSprite } from "./geodi-sprite";
import { t, useLocale, useSetLocale } from "./locale-context";

const repository = "https://github.com/mangowhoiscloud/geode";

export function LandingHeader({ home = false, current }: { home?: boolean; current?: "research" }) {
  const locale = useLocale();
  const setLocale = useSetLocale();
  const menuRef = useRef<HTMLDialogElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  // Landing order: run → evidence → research collection → install.
  const navigation = [
    { id: "run", label: t(locale, "실행", "Run") },
    { id: "evidence", label: t(locale, "측정", "Evidence") },
    { id: "research", label: t(locale, "연구", "Research") },
    { id: "install", label: t(locale, "설치", "Install") },
  ];
  const navigationLinks = (
    <>
      {navigation.map((item) => <a key={item.id} aria-current={current === item.id ? "page" : undefined} href={item.id === "research" ? `/geode/research/?lang=${locale}` : `${home ? "" : `/geode/?lang=${locale}`}#${item.id}`}>{item.label}</a>)}
      <Link href={`/docs?lang=${locale}`}>{t(locale, "문서", "Docs")}</Link>
      <Link href="/about">{t(locale, "만든 사람", "About the author")}</Link>
      <a href={repository}>GitHub</a>
    </>
  );

  return (
      <header className="landing-header">
        <div className="landing-container landing-nav-row">
          <a href={home ? "#hero" : `/geode/?lang=${locale}#hero`} className="landing-brand" aria-label={t(locale, "GEODE 처음으로", "GEODE home")}>
            <GeodiSprite scale={2} />
            <span>GEODE</span>
          </a>
          <nav className="landing-desktop-nav" aria-label={t(locale, "주 메뉴", "Main navigation")}>
            {navigationLinks}
          </nav>
          <div className="landing-locale" role="group" aria-label={t(locale, "언어", "Language")}>
            <button type="button" aria-pressed={locale === "ko"} onClick={() => setLocale("ko")}>KO</button>
            <button type="button" aria-pressed={locale === "en"} onClick={() => setLocale("en")}>EN</button>
          </div>
          <button ref={menuButtonRef} className="landing-mobile-menu" type="button" aria-haspopup="dialog" aria-controls="landing-menu"
            onClick={() => menuRef.current?.showModal()}>
            <Menu size={18} strokeWidth={1.5} aria-hidden="true" />
            <span>{t(locale, "메뉴", "Menu")}</span>
          </button>
          <dialog ref={menuRef} id="landing-menu" className="landing-menu-dialog" aria-labelledby="landing-menu-title"
            onClose={() => menuButtonRef.current?.focus()}
            onClick={event => { if (event.target === event.currentTarget) menuRef.current?.close(); }}>
            <div className="landing-menu-body">
              <div className="landing-menu-heading"><h2 id="landing-menu-title">{t(locale, "메뉴", "Menu")}</h2>
                <button type="button" onClick={() => menuRef.current?.close()}>{t(locale, "닫기", "Close")}</button></div>
            <nav
              aria-label={t(locale, "모바일 메뉴", "Mobile navigation")}
              onClick={(event) => {
                if (event.target instanceof Element && event.target.closest("a")) {
                  menuRef.current?.close();
                }
              }}
            >{navigationLinks}</nav>
            </div>
          </dialog>
        </div>
      </header>
  );
}
