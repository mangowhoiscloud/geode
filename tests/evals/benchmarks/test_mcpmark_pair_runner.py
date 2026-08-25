from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import subprocess
import sys
import zlib
from pathlib import Path

import pytest
from core.observability.trajectory import build_trajectory
from evals.benchmarks.mcpmark import pair_runner as pair

_MCPMARK_VERIFIER_PREIMAGES = {
    "tasks/filesystem/standard/desktop/project_management/verify.py": (
        "1f28a6a7a8b435a2ebfbef85f5b132e2fccf484f",
        (
            "c-qZc&2Aev5Wedv808STmF1*C8$f^y7_nRgh|$0{0u*VmpjMQ$_5PLIb*maa_E4bhsmB(5w?081p+j={yOdU2<&azgEr;I>hw}}G"
            "96x?^QZsroPx2Fz-=T6-t&9BmU^pBO-V&NDlNeV?ks}t<q^!`gpy-^i+o~whXXp(rz9VskE^&@mBqMo+ZZNx@qKhOY=!z6{h4bVm"
            "fgm6UNmdrLLTtkZOIl>8#ML@Y=BWAp27W4;f(-@>vP3IVMHOLHv`8o@E9ho)gpR)yveN;Ae}McIsZg~hhzlYuh=h)dSFdN+-(26!"
            "E~A^-^-XmC>I(6--eEf7MsWzCfEGoCPC@Ymh7(%k6VN>x2Idcs#H?hA"
            "a+sngOLO=?iW5fATb$NpMrlEVD5y~*90%4Ucn)q$7^39+"
            "8rHCA)KF5@G#3jVX<bLsJ9m7OHc{hgvWQB#C(O7jB0naqVk70msX!7woEJr^eJJ*O18&69mu*bTvl3JL&&YxZ_)zIWCurElk#lSp"
            "I`b!u!AHiQB~5bJihut46+LO=J+TbqXv?C`mGdkIUf`6G4%LZpTp!iaSTwIIzI7ZC8*@61Q0RaD+_f;N#|?=aS`#M@%%-!7)-ec?"
            "Ui*&IR7W3T^<3d4gh>Mq-*E-cg&9nIr#&<zKbBw%rvn>~gP%{b)L?EAS>Osskde|2OB|t;V45fSD)j9HP*;>N7F86-x7(yZqNr(1"
            "99&S%3eXq&23fTtw8DvCc~BxQ(iGMMIkIund*iGuVGQ(YU&$e!h2cxYvnNV&*QF+Mmvx#-nNx4OPV{sw+^|8<36Rh?XoAa<<cpEQ"
            "GO<q57F?TH+u)YNdxiLbMjoM#8UiQ=+W<aimx8pHQUW{xuDZi%vOrc;Ptm;%@z95`XEs?3Q8n{WObM=FEG{S?OgA0um8WmCgwvBn"
            "Ngi3j-kZg51Qrrl2!k<MaR;VU1=>QVgP3jMG_(AGbI8qq+e|j@<x+9Q@hxAtS%OvdViQ4J5H=|{Hl?y+K~nFVlMTEvp!yw2qZp@g"
            "onqKLZye$U%!NJmzLzQ9q`;0S6NQhMwvD-Z0fxH#Q;svjsT*9cMPc}<DD3<AL<6-*tY&qPSSZu9Yrw+%^6Ux`%!xQynq{xWGBMnn"
            "W)5~&BzLeZW_N~SPI&Yt*~{y<T?}*M?+}hTNc*zPJq!ap)824NrcS&_or@C?v^nqtA-5@%8S$Dd>Xi7yFr`i*P$BOXbm5OOQdT6J"
            "6B@BP%P<hk6X0h1-<J3eQg%fmI5t-;dm1h$Rgx2`5Dz7#c21a)?H&2pIB5bDmgSgxFeMFicieX{QU_bMFwE4YRxeg6sAEb}arQ!V"
            "-7bnBf+u0StUHLH8f6<fbpgtMm{KypO6`$d)T9MoWVoDU3y*mq5U(S+qbD)*M$Hy!>a_$EY2AUV+1dH!%=@T=pAvp)_eQm)s{%ra"
            "4<1TL*DqmKy4&!vF;cC-4@^<UH-;a~&236{M1BWFookH4Q)i?XSDl#%imE(hv%}c%wdx?&x+~klTz$n8XRLFj3$WLP3{ZH5Grqa{"
            "@boC?Oc#EE8q<|&j=Oms-;yfg#ps8iSHSQv$J$Q&*m&j!SDS3k_`!tRsjVY=JD8W%EQuY)Sq}!i_$H8$nY|y=ENutz%);4=Wvyos"
            "mt)c`0dC0wGy6mE!crFIgTJ_sjSXE}4~w;y0CZ3qdo!U+)6M|vdLQxM=pvGp)utB-S{T;LO~Q}>JSfh!f_;j>_N$|DtmeBC0yLiJ"
            "N4ACuT!^T6Sko<u*1T|N>~aKK7j?Qob0YmQ7O&fJk@J+rqvPFjA~+%l!-J=#^L?+t>DUzgekRT7juO5d<^^03<o|R*T1b#f#8N**"
            "`@=Oam<|K#+pQB9r=xcgf_x&E)Vp!wDTYe`|G%H+Q1gVN^y-`JSkzuk6A>OUEWKxV5FD?qKwV=d`eseEqP*rW9H?j*d3fi<JWB{$"
            "Vd{N%lVpm%7)z1I=nLl^ZJ+MR6ulVBxi8Fxe`jAr%|J@&i*2`&y_zsn^mHs>o;K&lNTh(H&Q8k|Js)cup6@KsI(jlw^vqt*vyLN9"
            "pgmY@$(w*M+ZJf!jJ@4;pP|G=p6WA)*}WP(7^s2M1|3ckl8@dktqg8DHR?nWhl%0!d*gJwsBv%~oqATg#f|TaP|Ihk5zxJh^)N;&"
            "$Po9o#s{w-<ZB3@eXo?1%o2?#y7y=Iu72!(=^AcmD4=IsHp(D6)$T&BxP+fFL#e;PSk}3$Xq~@WkVz!;R}!{?|Ni~QZ%8ID&cy%s"
            "Hyo46#CG>%fLSIvajj$(DJ7-s&yo1-RO+MQ*D7X}6%3v0bUKr%d)(ts9FE2oxIwyB=YjzX^vRvcO`g0^#qs59ZK46$(XMmAc;eJZ"
            "=a65~neI+^HzgdX*D94>s+6OFuS{!tzjsv!c;@8CHu}tMWA}U(a#UT4^!d`HPp#yom37B^-GALpQ+4u<sv>8iTpV}YAAAtO2OTt$"
            "2!1r~EHWKHG5w`v{y0!_G{Wy~UR~9>=r3&{78a?RF(A&VOd#qw;W7~~&5b5V8pz8el8o)t_-%fCe2nfj$OD4kRtjtiKMPscOWrNk"
            "vCvDIkHMo5+eo&E>?HMVK183Q;py;`&!6h+jDczwmXLK#CTq3?aP6E0NjED~;<Vu(S!>ey@%LXu;&U7YRp8n6wI$6qj91vzsIia0"
            "%7XQ70P5oG)$0({v!lTP))@(xM-e(bMZ+lKr$H1ACAd5q{sT8W>*@"
        ),
    ),
    "tasks/filesystem/standard/file_context/duplicates_searching/verify.py": (
        "c7a26ad9ce2fe5fb92079bcfd8755afdc5051ede",
        (
            "c-qZb+iu%N5PjEIOy~zott?x<N2m*=u^kwQlfrgW6pleq($Zd(B9+~xW7Y6u9}2X6>SK%kTfd;6(Aiy*yUU9#HR(mLVN=|hGnX^7"
            "!{y48^^~*qA&u8bd<)Z=xJlxzmgjk`H-yoUjsiiG82E_MsemwHa7-fthv_tu_XvkWBFIQB3gR)mX4gSXztd6|0smI%YSGCwVFLJ!"
            "w?dXoU>b;<hz=q9{!6^f*Cagu?<U}KQL8m3AzTyTBb@NZlp$WiX6+8FeXc|YEx-=~y&wX_4FS0jiiMyck5676oquzFadhfm9GzeI"
            "hbLzseZCD?PueI|C;*lu0uIoQ9^R%biF=6M_G;w4j*_Aw#3)h-Yjfm>1(Xwb6GSOFVk}{`S|Ed&kXT4-XfVVGQx1&0OVNjM2E&L*"
            "S*#px7g!w~ol"
            "y{t(g^e6hnOB;My{>?lYt&685J!qSP`t}xeS~h?x<ix5`vV1Q4$NZ#>9oqj8pHaz?D-H8-y;bvf*k60uG^BXc?WQ"
            "vNsv;w8I`F!MNS&^lr%Am|mkRZS5hs8xdsLk@}+;#eo=oQ$}Oa4!u8q`w>()K`Ns0wKn>`Fy~<a_v9f9n`OnTBqlmux02j5e_YVm"
            "(8?!wlndU@$!0}wm?TjVK2;wxq+6glXLMQ2)4GZ{x_C&k90b<EGdJ~On_I46FEg=Ij*SY<s#&~hnIhGMNg9u<aXAhmP9DRg>dzvW"
            "+Bz7fLb6z@3XC0(qUTzF{l3W)t>3MR3ziboD9GIu*OIYGuz$^xbXtTA6LO{nW$N<f#%0YYEd#@V<2|HfRu<Ukf@sF6$?FPyk*|^Z"
            "f|$Q249TuqVp+;I`@RUq3cQeL&>tvlf1}?MccPnJY|0C0(=jSS1EXB238trv?Rx{b^ehEl7d%Uach#*RZsv$vHsbbzh?^GTmW#OE"
            "gt(O>?%9a@3nFe=h<h&LeiPz$hS=Y*5c~ZF5w{JZR!|^n6?KR^Iiela{-ROcu@K#;_8X(Rn<MVnh`S3S?plaDF5+$z;$DupZzDck"
            "5OL2!+;<V5YD6XQP*c`vOy8w?uY0Vd^-^UT*Ug&WBxy9p3Y-Kq2K-4Fy{1^45G8utDe5|_(o18x=9wFyja~QhX?9tX>TkMEy4>B="
            "#8NU>^_!IT*PkS}WW3b&6hu*}wQ<~$ZwU+ui9zWDku>gNe{cJ0?7=AaNRKv~!3sRTA){}N8x5_RL%@j4Ws?s|+k|qC<ARPOnsKQa"
            "CZ}2j?Z?4{bTfshtkJ|C6=dS<zfy;klNzL`(&3Im#dw0qrAV$9vW`Ty5f_3r`+oj$T<Zl>9M8t>TxrMI+nuHL)77b7QVB9TR=+3X"
            "z~!iYSZ14lwqRcCp_}G_ta|KL;p>`Ts&<_IVS0wNr@3#`HmWl3-6m!tGl!)%!)o<dgtXXZm1%`%3v%qA;g=KKx=#G@c(qI(AE8v7"
            "RC+Rv{anjZ?23~L;g{yvhxAtsCc|qr&Hu77&ZBC^uSMEnonP}=TPIOZ-osMDxS)z?XiF1^>y$4=<yTAd<Pi>MGZ_+BkZVT8Y$@8>"
            "hXhclkWYKkCV{_LaX}~ulhXzI{eKxD41<HwjTKTQre~tc-1^Z<0a+GhrzX4upW%a-!&?bQ<J9H5HFKNun*6LrCO)K$X9>xupx~{2"
            "0Pm|V)iieS%Z;n*c92Uo6q#KR$HoLSN{8~^1na>ZJq+|AjYPERUt0o>_u3xi_d&y9S8i~p<@Aa|4#_Fce+EmSR;JGc<I7C$i)d@+"
            "$V)EUoWz^o05AK4tABAibhD+YvOu2Hx1~HaM$L&_;nCcbWrlZZJA8A}7B|7s_2j^!!{agH4M9?=9@8)+Om@GlN!ZMWTfSuc%I*Gn"
            "rM0TIO|h%4)j!Eqy4EB8UnC-kbTUSmaq)4EJ0&(Ye~w)-7>Q^G{cUaJ2b_Rn5lRE+42jStccUm(C&7)TQNc+R>Y(Hr%!nQ8GF3&L"
            "86^8RQzxE^M)LeqE^l|P=GfNw=vf*VOPJ-O)<uwyvW;g@1bMCj)qP4D(ce}#F<B{w!?`85s*=_2#8ef+3af#spQ65I38pJfCqwM0"
            "*?WgZ4|<lj_cag?U3jLf!P^zH79F%gReFbY<iU=C+-CB!Z1Oxrr}%XFspn5~Vs$D<xLf;8TbRZpXU;DQ<e>H)nB6-5{QZ}oKo_d4"
            "g(ctA^?E(enVSwth=ZJK9v5V)Pq6K;ef6~@brI>dXCoJpJkn?P-38vjbh>rQvfg|u53Op{*k@#pg0J-RpO!vTv$GMeIV5m|as0Nt"
            "!IZtuI*3s*|Dn*)mUs7)yt^AMm9e}&2we9aBUf(cnV8cs&eB*7F%9{|Teur@`5NOuQ#PMo<eF^k&EO<Sp~PIxfoie8jn~%J;J#4u"
            "0C??n$`hxhx!8+JlZ<0wsf1TBvvN;hgr||Pi{fqU!KdIIc%STS6z^+|s_N@3Yyzrs>_+5NPGVQiD49$nB2O5y1`*AkSl$(t`STB|"
            "$efVjUi<9)+*-|NTuyPKomooI$J+O8HL8xEoxH45)$g=g=&`SY@B46Y0G{tliu=B&mFuST7ou}Ow*"
        ),
    ),
    "tasks/filesystem/standard/file_context/file_splitting/verify.py": (
        "5f72271a6a4038ddf450c6c27b2e89214d4e253e",
        (
            "c-qxi&2A$_5Wf2<Dzk_6u!$3cxI{8ilsG6-7SK9c3GGIsj@@IocHA>`w?nMRM-E89i6e-2;|X{Ks;lRx+cVz8a6tHC&!p<BzptvR"
            "^WxxmrPcABkjGr!L$NlCTz=MzqNw+lE0KyRGa{Fur%DtC(p<r%$T&=jOc*2N9B!EYK=M7YEOKQ)uXQg~`4S3d7MZw%^8GjXSjptN"
            "*PHPa=G-KPYm>}`;!~5Wbw7rqFG%*Z2lzqcFS!A;;9v!z76h_!d38OWd^@=rzfNw(lbht?>J8XH?wJ}`rz`{+P<d`(goX$BXQ6UA"
            "K->MOLqCd1OQaxCrB-(C*pFgDb9l?L6(1{=t4<Us%`CYz)*Hd@Fl|DE;@_<>hFNJwakEmA0`AwgVwatJTY+_=ZLXUPCHz5Xqx)6f"
            "PDz>4c9-W_oi?i98Z*aS`Uu9$pM$BhR9nF;RnTw@5xsXJeqL(vLFrE1B&bkAVs8KZ{U^An&AlXzm!zELD_JGLOTs0~H2;Vtq3zcW"
            "OBKFz2kutJX4?X=Cg>+^R)D|#;3)3%&2zd`zELY4l!|3pS*{ejM7vV$RVhS(;YnF60&x++_rfe-nk(xLNVeqrmySOasLW^1ITU`E"
            "I+^5AoSu9-+YHQuiKxj12#G|ObKV~w!f+Vh62ekwjZNPG+&1V|&Azw3S?$nTQ#1RR*x7*kjpxU;ZY@~Wzn1S{TFa*aD+(@W{R%7&"
            "=oE-<vnVARy>=ol^{4O{sBHG(&)M@U`2?$QVz7)nNHD6oS?Ikf<$JMU_Z$clrVFMR7D=H$EBOzmf$vnqhfW5C3?P<_po@U}Go}7v"
            ")H)=`G?&Is;E_io#n}u`od?s816e<oibwd^FEQdqnm<fAo`z%kvd1IC+J=UGPSGg=)~sdLW99w^>BW6Y?WWZWIA8GT2g_kw%_`wc"
            "m4&PbZr#;*uKA(FF&vCw*iCmj%zZf9aRhnl9Ia5EOZ~Lwev51lX$$w=$?c}0;ZvPZmLfq*e6EC9@6`yXjq42N9;Z^+m*k&4By%O^"
            "LNe$5KHX3$Qk!mxWlYUE{h{G^S=Kj5ipFReUav*v8ol9jV6esMCm6b$ok0S&3A&S<O=7pFO|R_2I`LizWp@9c)1ot`SEHbY|JAI>"
            "mxb+R-xVAVogN>ITIA|nug?A6sg!3qcPrMCndu_rj^}F?AO8Hh5~+uQ9a-BR#G7vIz=;5%E4FyA<GM3IiVI^5BEyp6u*%j?%qp4V"
            "`ezh#tHWM{O6EYS!P<Zg(y_+>`z7%4`Agu25HR>^A94BvYERn#tcJI+<4C8C-O?|$`@2=@mpG+6b&3!xfIiytwc@d-vSXroxudPU"
            "_NvL7?WYE3FQ$AIR;P`<ix^8LWVO9w*<RzLBTIG5PFHeje}q?8SJSSmvhUenfBgD0I1<^((Q!*33<go`&xs433dutkwBd!zwEsGx"
            "*LK0H)6|dL1*y5=jcGlP4nKZxjSoEtyC*o9OUfldGzgv7sQ_S1CpQIq?G}ngyS+9Cs^?{oUsbzAquE+B0!6I9V;K3|XoU@5s@w*r"
            "{YujLxFh2>+=6M118C%EQyq_1Cb3;s8?#h_E&jMFwR_^dJUTjp#~Ne<`0O#hyl8pI^|ac$YXu&*&Yepdk&5e8W_)VCml3>zXcT?&"
            "`APlHl?JMP-e8kaNp;O%gZ#y*yeu;A<}=-%vh_jhpuk4><wxRskQ*GkXOoF1t=HOKC{4d~iDNLGCtnBD<=NGB7t}EB^)R%AvYaF^"
            "!W}0`Y}+SE<iOnw_#04aCK~"
        ),
    ),
}
_TOOL_SCHEMA_SHA256 = "c" * 64


def _fixture(category: str = "desktop") -> dict[str, object]:
    return {
        "categories": [
            {
                "category": category,
                "directory_count": 1,
                "file_count": 1,
                "bytes": 1,
                "sha256": "a" * 64,
                "semantic_sha256": "c" * 64,
            }
        ],
        "aggregate_sha256": "b" * 64,
        "semantic_aggregate_sha256": "d" * 64,
    }


def test_pair_runner_delegates_run_spec_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.eval import contract

    def reject(_path: Path) -> dict[str, object]:
        raise ValueError("privacy contract rejected")

    monkeypatch.setattr(contract, "validate_run_spec", reject)

    with pytest.raises(pair.PairRunError, match="privacy contract rejected"):
        pair.validate_run_spec(tmp_path / "run-spec.json")


def _write_native(
    native_dir: Path,
    *,
    task: str,
    arm: str,
    model: str,
    effort: str,
    timeout: int,
    timed_surface: str = "adapter_execute_entry_through_native_runtime_return",
    max_tool_result_tokens: int | None = None,
    timed_out: bool = False,
) -> None:
    task_dir = native_dir / "run" / "model__filesystem" / "run-1" / "desktop__task"
    task_dir.mkdir(parents=True)
    (task_dir / "meta.json").write_text(
        json.dumps(
            {
                "task_name": task.replace("/", "__"),
                "model_name": model,
                "reasoning_effort": effort,
                "mcp": "filesystem",
                "timeout": timeout,
                "execution_result": {
                    "success": not timed_out,
                    "error_message": "time_budget_expired" if timed_out else None,
                    "verification_output": "FAIL" if timed_out else "PASS",
                },
            }
        ),
        encoding="utf-8",
    )
    (task_dir.parent / "summary.json").write_text(
        json.dumps(
            {
                "total_tasks": 1,
                "successful_tasks": int(not timed_out),
                "failed_tasks": int(timed_out),
                "model_config": {"model_name": model, "agent_name": arm},
            }
        ),
        encoding="utf-8",
    )
    trajectory = build_trajectory(
        trajectory_id=f"test-{arm}",
        source={
            "harness": "mcpmark",
            "run": f"run-{arm}",
            "session": f"session-{arm}",
            "task": "c" * 64,
            "parents": [],
        },
        events=[
            {
                "kind": "user_message",
                "actor": "user",
                "turn_id": "turn-1",
                "payload": {"content": "task"},
            },
            {
                "kind": "assistant_message",
                "actor": "assistant",
                "turn_id": "turn-1",
                "payload": {"content": "done"},
            },
        ],
        outcome={"success": not timed_out},
        provenance={
            "model": model.removeprefix(f"{arm}-"),
            "source": "subscription",
            "effort": effort,
        },
        privacy={"review_state": "local"},
        integrity={
            "scope_complete": not timed_out,
            "scope_incompleteness": (
                ["MCPMark action deadline right-censored the turn"] if timed_out else []
            ),
        },
    )
    (task_dir / "execution.trajectory.json").write_text(json.dumps(trajectory), encoding="utf-8")
    deadline = {
        "schema_id": "geode.mcpmark.execution_deadline@1",
        "arm": arm,
        "timeout_owner": "adapter",
        "timed_surface": timed_surface,
        "clock": "monotonic",
        "limit_seconds": float(timeout),
        "action_started_monotonic": 100.0,
        "action_deadline_monotonic": 100.0 + timeout,
        "action_finished_monotonic": 100.0 + timeout if timed_out else 101.0,
        "action_elapsed_seconds": float(timeout) if timed_out else 1.0,
        "expired": timed_out,
        "action_status": "right_censored" if timed_out else "complete",
        "cleanup_grace_seconds": 5.0,
        "cleanup_elapsed_seconds": 0.1,
        "cleanup_status": "complete",
        "evidence_status": "written",
        "started_at_unix_seconds": 1_000.0,
        "finished_at_unix_seconds": 1_002.0,
    }
    if max_tool_result_tokens is not None:
        deadline["runtime_config"] = {
            "max_tool_result_tokens": max_tool_result_tokens,
            "offload_store_bound": False,
            "tool_schema_sha256": _TOOL_SCHEMA_SHA256,
        }
    (task_dir / "execution.deadline.json").write_text(
        json.dumps(deadline),
        encoding="utf-8",
    )
    (task_dir / "messages.json").write_text("[]", encoding="utf-8")
    (task_dir / "execution.log").write_text("[]", encoding="utf-8")


def test_filesystem_30_order_and_hash_are_frozen() -> None:
    assert pair.EXPECTED_FS30_SHA256 == (
        "50483308573ce407abaf0700885d56c6df0453557669dddce9edcece83710433"
    )
    assert pair._arm_order(1) == ("geode", "codex")
    assert pair._arm_order(2) == ("codex", "geode")
    assert pair._workload_hash(pair.TOOL_CAP_IDS) == pair.TOOL_CAP_SHA256
    assert pair._tool_cap_arm_order(1, 1) == pair.TOOL_CAP_ARMS
    assert pair._tool_cap_arm_order(1, 2) == pair.TOOL_CAP_ARMS[::-1]
    assert pair._tool_cap_arm_order(2, 1) == pair.TOOL_CAP_ARMS[::-1]
    schedule = pair._execution_schedule(pair.TOOL_CAP_PROFILE, pair.TOOL_CAP_IDS)
    assert len(schedule) == 30
    assert {row[4] for row in schedule} == {"geode"}
    assert [(row[2], row[5]) for row in schedule] == [
        (task, cap)
        for repetition in range(1, 4)
        for index, task in enumerate(pair.TOOL_CAP_IDS, start=1)
        for _label, cap in pair._tool_cap_arm_order(index, repetition)
    ]
    pair_schedule = pair._execution_schedule(pair.PAIR_PROFILE, ("desktop/first",))
    assert [(row[4], row[5]) for row in pair_schedule] == [
        ("geode", pair.PAIR_MAX_TOOL_RESULT_TOKENS),
        ("codex", None),
    ]
    patch = Path(pair.__file__).with_name("patches") / (
        "mcpmark-cd45b7f-filesystem-standard-verifier-missing-output.patch"
    )
    assert pair._sha256(patch) == pair.PATCH_SHA256


def test_fixture_semantic_digest_covers_mtime_and_empty_directories(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    source = fixture / "source.txt"
    source.write_text("same bytes", encoding="utf-8")
    os.utime(source, ns=(1_700_000_000_000_000_000,) * 2)
    original = pair._tree_row(fixture, category="fixture")
    assert original["directory_count"] == 1

    original_mode = fixture.stat().st_mode & 0o7777
    os.chmod(fixture, 0o700 if original_mode != 0o700 else 0o755)
    changed_root_mode = pair._tree_row(fixture, category="fixture")
    assert changed_root_mode["sha256"] == original["sha256"]
    assert changed_root_mode["semantic_sha256"] != original["semantic_sha256"]
    os.chmod(fixture, original_mode)

    os.utime(source, ns=(1_700_000_001_000_000_000,) * 2)
    changed_mtime = pair._tree_row(fixture, category="fixture")
    assert changed_mtime["sha256"] == original["sha256"]
    assert changed_mtime["semantic_sha256"] != original["semantic_sha256"]

    (fixture / "empty").mkdir()
    changed_structure = pair._tree_row(fixture, category="fixture")
    assert changed_structure["directory_count"] == 2
    assert changed_structure["semantic_sha256"] != changed_mtime["semantic_sha256"]


def test_verifier_patch_applies_to_exact_preimages_and_compiles(tmp_path: Path) -> None:
    expected_functions = {
        "tasks/filesystem/standard/desktop/project_management/verify.py": (
            "verify_progress_tracking_empty",
            "verify_file_counts",
        ),
        "tasks/filesystem/standard/file_context/duplicates_searching/verify.py": (
            "verify_total_file_count",
        ),
        "tasks/filesystem/standard/file_context/file_splitting/verify.py": (
            "verify_no_extra_files",
        ),
    }
    for relative, (expected_blob, encoded) in _MCPMARK_VERIFIER_PREIMAGES.items():
        raw = zlib.decompress(base64.b85decode(encoded))
        blob = hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw,
            usedforsecurity=False,
        ).hexdigest()
        assert blob == expected_blob
        target = tmp_path / relative
        target.parent.mkdir(parents=True)
        target.write_bytes(raw)

    patch = Path(pair.__file__).with_name("patches") / (
        "mcpmark-cd45b7f-filesystem-standard-verifier-missing-output.patch"
    )
    checked = subprocess.run(  # noqa: S603 - fixed git argv over temp fixtures
        ("git", "apply", "--check", str(patch)),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert checked.returncode == 0, checked.stderr
    subprocess.run(  # noqa: S603 - fixed git argv over temp fixtures
        ("git", "apply", str(patch)),
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    for relative, expected_sha256 in pair.PATCHED_VERIFIERS.items():
        target = tmp_path / relative
        source = target.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative)
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        for name in expected_functions[relative]:
            body = ast.get_source_segment(source, functions[name])
            assert body is not None
            assert body.index(".is_dir()") < body.index(".iterdir()")
        assert pair._sha256(target) == expected_sha256


def test_tool_cap_spec_freezes_model_budget_and_diagnostic_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = {
        "preregistration": {"mode": "prospective"},
        "study": {
            "research_question": (
                "Does removing the 25K tool-result guard on the same large-result MCP tasks "
                "increase verifier accuracy and change rereads, fresh input tokens, and wall time?"
            ),
            "hypothesis": (
                "Across 15 task-repetitions per arm, unlimited-0 produces more verifier passes "
                "than guard-25000."
            ),
            "primary_metric": {
                "name": "verifier-pass-rate arm delta",
                "unit": "ratio",
                "direction": "target",
                "aggregation": "(sum(unlimited-0 passes) - sum(guard-25000 passes)) / 15",
                "denominator": 15,
            },
            "decision_rule": (
                "supported if unlimited-0 passes exceed guard-25000 passes; "
                "mixed if equal; not-supported if lower"
            ),
            "invalidation_rule": (
                "Invalidate the run if any attempt changes the frozen deadline or identity "
                "contract, cannot bind the arm cap or reconstruct truncation, fails fixture "
                "cleanup or reset, lacks native result, verifier, or trajectory evidence, or "
                "exits on an unrecovered provider quota or transport error."
            ),
            "analysis_plan": (
                "Select all 30 fresh attempts; compute the signed verifier-pass-rate arm delta "
                "as (unlimited-0 passes - guard-25000 passes) / 15; report secondary token, "
                "wall-time, MCP call/error, reread, and truncation metrics for explanation only; "
                "preserve infrastructure-invalid attempts and do not replace or score them."
            ),
        },
        "reproduction": {
            "execution": {
                "timeout_seconds": 1200,
                "seed_schedule": ["upstream-run-1", "upstream-run-2", "upstream-run-3"],
                "budget": {"kind": "wall-time", "limit": 1200, "unit": "seconds"},
            },
            "model": {"label": "gpt-5.4", "reasoning": "high"},
            "comparison": {"claim_class": "diagnostic", "promotion_authority": "none"},
        },
    }
    monkeypatch.setattr(pair, "_validate_spec", lambda *_args, **_kwargs: spec)

    assert (
        pair._validate_tool_cap_spec(
            tmp_path / "run-spec.json",
            fixture_semantic_sha256="a" * 64,
        )
        is spec
    )

    spec["reproduction"]["model"]["reasoning"] = "medium"
    with pytest.raises(pair.PairRunError, match=r"GPT-5\.4/high"):
        pair._validate_tool_cap_spec(
            tmp_path / "run-spec.json",
            fixture_semantic_sha256="a" * 64,
        )

    spec["reproduction"]["model"]["reasoning"] = "high"
    for field, bad_value in (("name", "accuracy"), ("direction", "minimize")):
        original = spec["study"]["primary_metric"][field]
        spec["study"]["primary_metric"][field] = bad_value
        with pytest.raises(pair.PairRunError, match="frozen primary metric"):
            pair._validate_tool_cap_spec(
                tmp_path / "run-spec.json",
                fixture_semantic_sha256="a" * 64,
            )
        spec["study"]["primary_metric"][field] = original

    spec["study"]["decision_rule"] = "always supported"
    with pytest.raises(pair.PairRunError, match="frozen decision rule"):
        pair._validate_tool_cap_spec(
            tmp_path / "run-spec.json",
            fixture_semantic_sha256="a" * 64,
        )

    spec["study"]["decision_rule"] = (
        "supported if unlimited-0 passes exceed guard-25000 passes; "
        "mixed if equal; not-supported if lower"
    )
    mutations = (
        (spec["preregistration"], "mode", "retrospective", "prospective preregistration"),
        (spec["reproduction"]["execution"]["budget"], "limit", 1, "wall-time budget"),
        (spec["study"], "research_question", "changed", "research question"),
        (spec["study"], "hypothesis", "changed", "hypothesis"),
        (spec["study"], "invalidation_rule", "changed", "invalidation rule"),
        (spec["study"], "analysis_plan", "changed", "analysis plan"),
    )
    for target, field, bad_value, message in mutations:
        original = target[field]
        target[field] = bad_value
        with pytest.raises(pair.PairRunError, match=message):
            pair._validate_tool_cap_spec(
                tmp_path / "run-spec.json",
                fixture_semantic_sha256="a" * 64,
            )
        target[field] = original


def test_pair_spec_freezes_model_budget_metric_and_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = ("desktop/first", "desktop/second")
    spec = {
        "preregistration": {"mode": "prospective"},
        "study": pair._pair_study_contract(denominator=len(ids), smoke=False),
        "reproduction": {
            "execution": {
                "timeout_seconds": 1200,
                "seed_schedule": ["upstream-run-1"],
                "budget": {"kind": "wall-time", "limit": 1200, "unit": "seconds"},
            },
            "model": {"label": "gpt-5.4", "reasoning": "high"},
            "comparison": {
                "claim_class": "diagnostic",
                "comparator": pair.CODEX_COMPARATOR,
                "comparability": "direct",
                "promotion_authority": "none",
            },
        },
    }
    monkeypatch.setattr(pair, "_validate_spec", lambda *_args, **_kwargs: spec)

    assert (
        pair._validate_pair_spec(
            tmp_path / "run-spec.json",
            ids=ids,
            fixture_semantic_sha256="a" * 64,
            smoke=False,
        )
        is spec
    )

    spec["reproduction"]["comparison"]["promotion_authority"] = "paired-runtime"
    with pytest.raises(pair.PairRunError, match="comparison contract"):
        pair._validate_pair_spec(
            tmp_path / "run-spec.json",
            ids=ids,
            fixture_semantic_sha256="a" * 64,
            smoke=False,
        )

    spec["reproduction"]["comparison"]["promotion_authority"] = "none"
    spec["study"]["analysis_plan"] = "changed after preregistration"
    with pytest.raises(pair.PairRunError, match="frozen analysis plan"):
        pair._validate_pair_spec(
            tmp_path / "run-spec.json",
            ids=ids,
            fixture_semantic_sha256="a" * 64,
            smoke=False,
        )


def test_pair_smoke_contract_uses_receipt_coverage() -> None:
    contract = pair._pair_study_contract(denominator=1, smoke=True)
    assert contract["primary_metric"] == {
        "name": "accepted paired-task coverage",
        "unit": "ratio",
        "direction": "maximize",
        "aggregation": "accepted paired tasks / 1",
        "denominator": 1,
    }


def test_pair_full_contract_preserves_the_canonical_ten_point_threshold() -> None:
    contract = pair._pair_study_contract(denominator=30, smoke=False)
    assert contract["hypothesis"] == (
        "Across the frozen 30-task workload, GEODE verifier accuracy is no more than 10 "
        "percentage points below Codex verifier accuracy."
    )
    assert contract["decision_rule"] == (
        "supported if the GEODE-minus-Codex verifier-pass-rate delta is at least -0.10; "
        "not-supported if lower"
    )
    assert contract["primary_metric"] == {
        "name": "GEODE minus Codex verifier-pass-rate delta",
        "unit": "ratio",
        "direction": "target",
        "aggregation": "(sum(geode passes) - sum(codex passes)) / 30",
        "denominator": 30,
    }


def test_codex_cli_preflight_binds_version_source_and_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "codex"
    executable.write_bytes(b"frozen codex binary")
    executable.chmod(0o755)
    monkeypatch.setattr(pair.shutil, "which", lambda _name: str(executable))
    monkeypatch.setattr(pair, "CODEX_CLI_EXECUTABLE_SHA256", pair._sha256(executable))
    monkeypatch.setattr(
        pair,
        "_run_process",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=pair.CODEX_CLI_VERSION + "\n", stderr=""
        ),
    )

    receipt, resolved = pair._codex_cli_preflight(tmp_path)
    assert receipt == {
        "command": "codex",
        "version": pair.CODEX_CLI_VERSION,
        "source_revision": pair.CODEX_CLI_SOURCE_REVISION,
        "executable_sha256": pair._sha256(executable),
    }
    assert resolved == executable

    monkeypatch.setattr(
        pair,
        "_run_process",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="codex-cli 0.146.0\n", stderr=""
        ),
    )
    with pytest.raises(pair.PairRunError, match="must be exactly"):
        pair._codex_cli_preflight(tmp_path)


def test_spec_rejects_a_digest_outside_the_selected_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = ("desktop/first",)
    spec = {
        "preregistration": {"live_test_approved": True},
        "reproduction": {
            "execution": {
                "ordered_workload_ids": list(ids),
                "workload_ids_sha256": "0" * 64,
                "repetitions": 1,
                "max_concurrency": 1,
                "timeout_seconds": 1200,
            },
            "harness": {"revision": f"harness+patch-sha256:{pair.PATCH_SHA256}"},
            "environment": {"initial_state_ref": "fixture-semantic-sha256:" + "a" * 64},
            "model": {
                "provider": "openai",
                "route": "subscription",
                "label": "gpt-5.4",
                "reasoning": "high",
            },
            "geode": {"revision": "head", "dirty": False},
        },
    }
    monkeypatch.setattr(pair, "validate_run_spec", lambda _path: spec)
    monkeypatch.setattr(
        pair,
        "get_benchmark",
        lambda _name: type("Benchmark", (), {"commit": "harness"})(),
    )
    monkeypatch.setattr(
        pair,
        "_git",
        lambda _root, *args: "head" if args[0] == "rev-parse" else "",
    )

    with pytest.raises(pair.PairRunError, match="workload digest"):
        pair._validate_spec(tmp_path / "run-spec.json", ids=ids, fixture_semantic_sha256="a" * 64)


def test_python_preflight_checks_clean_dependencies_and_source_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def run(command: tuple[str, ...], **kwargs: object):
        calls.append((command, kwargs))
        return pair.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(pair, "_run_process", run)

    receipt = pair._python_preflight(Path("/repo/.venv/bin/python"), tmp_path)

    assert calls[0][0][-3:] == ("-m", "pip", "check")
    assert calls[1][0][1] == "-c"
    assert "import pipeline" in calls[1][0][2]
    assert "create_task_manager('filesystem', task_suite='standard')" in calls[1][0][2]
    assert "create_state_manager('filesystem')" in calls[1][0][2]
    assert calls[2][0] == ("npx", "--version")
    assert all(call[1]["cwd"] == tmp_path for call in calls)
    assert receipt["dependency_check"] == "pass"


def test_python_preflight_rejects_a_dependency_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pair,
        "_run_process",
        lambda command, **_kwargs: pair.subprocess.CompletedProcess(command, 1),
    )

    with pytest.raises(pair.PairRunError, match="dependency integrity"):
        pair._python_preflight(Path("/repo/.venv/bin/python"), tmp_path)


def test_filesystem_tool_schema_probe_hashes_sorted_raw_schemas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schemas = [
        {"name": "write", "inputSchema": {"type": "object"}},
        {"inputSchema": {"type": "object"}, "name": "read"},
    ]
    monkeypatch.setattr(
        pair,
        "_run_process",
        lambda *_args, **_kwargs: pair.subprocess.CompletedProcess(
            (), 0, stdout=json.dumps(schemas).encode(), stderr=b""
        ),
    )

    assert pair._probe_filesystem_tool_schema(Path("python"), tmp_path) == (
        pair._tool_schema_sha256(schemas[::-1])
    )


def test_filesystem_tool_schema_probe_has_a_hard_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("schema-probe", 60)

    monkeypatch.setattr(pair, "_run_process", timeout)

    with pytest.raises(pair.PairRunError, match="tool-schema probe timed out"):
        pair._probe_filesystem_tool_schema(Path("python"), tmp_path)


def test_invoke_arm_sets_the_tool_cap_only_in_the_child_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}
    parent_value = os.environ.get("GEODE_MAX_TOOL_RESULT_TOKENS")

    def run(command, **kwargs):
        captured.update(kwargs["env"])
        return pair.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(pair.subprocess, "run", run)
    pair._invoke_arm(
        python=Path("python"),
        mcpmark_root=tmp_path,
        native_dir=tmp_path / "native",
        log_dir=tmp_path / "logs",
        task="legal_document/dispute_review",
        arm="geode",
        model_label="gpt-5.4",
        effort="high",
        timeout=1200,
        run_id="tool-cap-test",
        max_tool_result_tokens=0,
    )

    assert captured["GEODE_MAX_TOOL_RESULT_TOKENS"] == "0"
    assert os.environ.get("GEODE_MAX_TOOL_RESULT_TOKENS") == parent_value


def test_invoke_arm_passes_the_frozen_codex_binary_only_to_codex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}
    executable = tmp_path / "codex"

    def run(command, **kwargs):
        captured.update(kwargs["env"])
        return pair.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(pair.subprocess, "run", run)
    pair._invoke_arm(
        python=Path("python"),
        mcpmark_root=tmp_path,
        native_dir=tmp_path / "native",
        log_dir=tmp_path / "logs",
        task="desktop/task",
        arm="codex",
        model_label="gpt-5.4",
        effort="high",
        timeout=1200,
        run_id="pair-test",
        codex_executable=executable,
    )

    assert captured["GEODE_MCPMARK_CODEX_BIN"] == str(executable)


def test_pair_runner_is_serial_counterbalanced_and_uses_fresh_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out"
    output.mkdir()
    root = tmp_path / "mcpmark"
    fixture_dir = root / "test_environments/desktop"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "seed").write_text("x", encoding="utf-8")
    ids = ("desktop/first", "desktop/second")
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(pair, "_tree_row", lambda *_args, **_kwargs: _fixture()["categories"][0])

    def invoke(**kwargs: object) -> tuple[int, Path, Path]:
        native_dir = kwargs["native_dir"]
        log_dir = kwargs["log_dir"]
        assert isinstance(native_dir, Path) and not native_dir.exists()
        assert isinstance(log_dir, Path) and not log_dir.exists()
        log_dir.mkdir(parents=True)
        stdout = log_dir / "stdout.log"
        stderr = log_dir / "stderr.log"
        stdout.write_text("ok", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        arm = str(kwargs["arm"])
        task = str(kwargs["task"])
        _write_native(
            native_dir,
            task=task,
            arm=arm,
            model=f"{arm}-gpt-5.4",
            effort="high",
            timeout=1200,
            max_tool_result_tokens=(kwargs["max_tool_result_tokens"] if arm == "geode" else None),
        )
        calls.append((task, arm))
        return 0, stdout, stderr

    monkeypatch.setattr(pair, "_invoke_arm", invoke)
    pair._run_tasks(
        output_dir=output,
        mcpmark_root=root,
        python=Path("python"),
        ids=ids,
        fixture=_fixture(),
        run_id="paired-test",
        model_label="gpt-5.4",
        effort="high",
        timeout=1200,
        tool_schema_sha256=_TOOL_SCHEMA_SHA256,
    )

    assert calls == [
        ("desktop/first", "geode"),
        ("desktop/first", "codex"),
        ("desktop/second", "codex"),
        ("desktop/second", "geode"),
    ]
    rows = [json.loads(line) for line in (output / "runner-events.jsonl").read_text().splitlines()]
    assert [row["sequence"] for row in rows] == list(range(len(rows)))
    assert rows[0]["event"] == "run_started"
    assert rows[-1] == {
        **rows[-1],
        "event": "run_completed",
        "completed_tasks": 2,
        "completed_arms": 4,
    }
    result = json.loads((output / "runner-result.json").read_text(encoding="utf-8"))
    assert result["arms"] == {
        "codex": {"attempts": 2, "passes": 2},
        "geode": {"attempts": 2, "passes": 2},
    }
    assert result["source_events"]["sha256"] == pair._sha256(output / "runner-events.jsonl")
    assert result["primary_metric"] == {
        "name": "GEODE minus Codex verifier-pass-rate delta",
        "value": 0.0,
        "numerator": 0,
        "denominator": 2,
    }


def test_pair_smoke_result_records_coverage_despite_different_verifier_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out"
    output.mkdir()
    root = tmp_path / "mcpmark"
    (root / "test_environments/desktop").mkdir(parents=True)
    monkeypatch.setattr(pair, "_tree_row", lambda *_args, **_kwargs: _fixture()["categories"][0])

    def invoke(**kwargs: object) -> tuple[int, Path, Path]:
        native_dir = kwargs["native_dir"]
        log_dir = kwargs["log_dir"]
        assert isinstance(native_dir, Path) and isinstance(log_dir, Path)
        native_dir.mkdir(parents=True)
        log_dir.mkdir(parents=True)
        stdout = log_dir / "stdout.log"
        stderr = log_dir / "stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return 0, stdout, stderr

    monkeypatch.setattr(pair, "_invoke_arm", invoke)
    monkeypatch.setattr(
        pair,
        "_native_receipt",
        lambda _path, **kwargs: {
            "task_sha256": "a" * 64,
            "verifier_pass": kwargs["arm"] == "geode",
        },
    )
    pair._run_tasks(
        output_dir=output,
        mcpmark_root=root,
        python=Path("python"),
        ids=("desktop/task",),
        fixture=_fixture(),
        run_id="smoke-test",
        model_label="gpt-5.4",
        effort="high",
        timeout=1200,
        tool_schema_sha256=_TOOL_SCHEMA_SHA256,
        profile=pair.PAIR_SMOKE_PROFILE,
    )

    result = json.loads((output / "runner-result.json").read_text(encoding="utf-8"))
    assert result["arms"] == {
        "codex": {"attempts": 1, "passes": 0},
        "geode": {"attempts": 1, "passes": 1},
    }
    assert result["primary_metric"] == {
        "name": "accepted paired-task coverage",
        "value": 1.0,
        "numerator": 1,
        "denominator": 1,
    }


@pytest.mark.parametrize(
    ("guard_passes", "unlimited_passes", "numerator"),
    ((1, 2, 1), (2, 2, 0), (2, 1, -1)),
)
def test_tool_cap_result_records_a_signed_digest_bound_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    guard_passes: int,
    unlimited_passes: int,
    numerator: int,
) -> None:
    output = tmp_path / f"out-{numerator}"
    output.mkdir()
    root = tmp_path / "mcpmark"
    (root / "test_environments/desktop").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pair, "_tree_row", lambda *_args, **_kwargs: _fixture()["categories"][0])

    def invoke(**kwargs: object) -> tuple[int, Path, Path]:
        native_dir = kwargs["native_dir"]
        log_dir = kwargs["log_dir"]
        assert isinstance(native_dir, Path) and isinstance(log_dir, Path)
        native_dir.mkdir(parents=True)
        log_dir.mkdir(parents=True)
        stdout = log_dir / "stdout.log"
        stderr = log_dir / "stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return 0, stdout, stderr

    remaining = {25_000: guard_passes, 0: unlimited_passes}

    def receipt(_native_dir: Path, **kwargs: object) -> dict[str, object]:
        cap = kwargs["expected_tool_cap"]
        assert isinstance(cap, int)
        passed = remaining[cap] > 0
        remaining[cap] -= int(passed)
        return {"task_sha256": "a" * 64, "verifier_pass": passed}

    monkeypatch.setattr(pair, "_invoke_arm", invoke)
    monkeypatch.setattr(pair, "_native_receipt", receipt)
    pair._run_tasks(
        output_dir=output,
        mcpmark_root=root,
        python=Path("python"),
        ids=("desktop/task",),
        fixture=_fixture(),
        run_id="tool-cap-test",
        model_label="gpt-5.4",
        effort="high",
        timeout=1200,
        tool_schema_sha256=_TOOL_SCHEMA_SHA256,
        profile=pair.TOOL_CAP_PROFILE,
    )

    result = json.loads((output / "runner-result.json").read_text(encoding="utf-8"))
    assert result["primary_metric"] == {
        "name": "verifier-pass-rate arm delta",
        "value": numerator / 3,
        "numerator": numerator,
        "denominator": 3,
    }
    assert result["source_events"]["sha256"] == pair._sha256(output / "runner-events.jsonl")


def test_pair_runner_stops_before_the_next_arm_on_infrastructure_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out"
    output.mkdir()
    root = tmp_path / "mcpmark"
    (root / "test_environments/desktop").mkdir(parents=True)
    monkeypatch.setattr(pair, "_tree_row", lambda *_args, **_kwargs: _fixture()["categories"][0])
    calls = 0

    def invoke(**kwargs: object) -> tuple[int, Path, Path]:
        nonlocal calls
        calls += 1
        log_dir = kwargs["log_dir"]
        assert isinstance(log_dir, Path)
        log_dir.mkdir(parents=True)
        stdout = log_dir / "stdout.log"
        stderr = log_dir / "stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("failed", encoding="utf-8")
        return 9, stdout, stderr

    monkeypatch.setattr(pair, "_invoke_arm", invoke)
    with pytest.raises(pair.PairRunError, match="exited 9"):
        pair._run_tasks(
            output_dir=output,
            mcpmark_root=root,
            python=Path("python"),
            ids=("desktop/first",),
            fixture=_fixture(),
            run_id="paired-test",
            model_label="gpt-5.4",
            effort="high",
            timeout=1200,
            tool_schema_sha256=_TOOL_SCHEMA_SHA256,
        )

    assert calls == 1
    rows = [json.loads(line) for line in (output / "runner-events.jsonl").read_text().splitlines()]
    assert rows[-1]["event"] == "run_stopped"
    assert rows[-1]["failure_class"] == "infrastructure"


def test_pair_runner_rejects_fixture_drift_after_the_last_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out"
    output.mkdir()
    root = tmp_path / "mcpmark"
    (root / "test_environments/desktop").mkdir(parents=True)
    baseline = _fixture()["categories"][0]
    changed = {**baseline, "semantic_sha256": "e" * 64}
    rows = iter((baseline, changed))
    monkeypatch.setattr(pair, "_tree_row", lambda *_args, **_kwargs: next(rows))

    def invoke(**kwargs: object) -> tuple[int, Path, Path]:
        log_dir = kwargs["log_dir"]
        assert isinstance(log_dir, Path)
        log_dir.mkdir(parents=True)
        stdout = log_dir / "stdout.log"
        stderr = log_dir / "stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return 0, stdout, stderr

    monkeypatch.setattr(pair, "_invoke_arm", invoke)
    monkeypatch.setattr(
        pair,
        "_native_receipt",
        lambda *_args, **_kwargs: {"task_sha256": "a" * 64, "verifier_pass": True},
    )

    with pytest.raises(pair.PairRunError, match="changed during a paired arm"):
        pair._run_tasks(
            output_dir=output,
            mcpmark_root=root,
            python=Path("python"),
            ids=("desktop/first",),
            fixture=_fixture(),
            run_id="paired-test",
            model_label="gpt-5.4",
            effort="high",
            timeout=1200,
            tool_schema_sha256=_TOOL_SCHEMA_SHA256,
        )

    assert not (output / "runner-result.json").exists()


def test_pair_runner_refuses_preexisting_fixture_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out"
    output.mkdir()
    root = tmp_path / "mcpmark"
    (root / ".mcpmark_backups/stale").mkdir(parents=True)
    monkeypatch.setattr(pair, "_tree_row", lambda *_args, **_kwargs: _fixture()["categories"][0])
    with pytest.raises(pair.PairRunError, match="not empty before"):
        pair._run_tasks(
            output_dir=output,
            mcpmark_root=root,
            python=Path("python"),
            ids=("desktop/first",),
            fixture=_fixture(),
            run_id="paired-test",
            model_label="gpt-5.4",
            effort="high",
            timeout=1200,
            tool_schema_sha256=_TOOL_SCHEMA_SHA256,
        )


def test_pair_runner_rejects_an_exception_shaped_verifier_receipt(tmp_path: Path) -> None:
    native = tmp_path / "native"
    _write_native(
        native,
        task="desktop/task",
        arm="geode",
        model="geode-gpt-5.4",
        effort="high",
        timeout=1200,
    )
    meta_path = next(native.rglob("meta.json"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["execution_result"]["verification_error"] = (
        "Traceback (most recent call last):\nFileNotFoundError"
    )
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(pair.PairRunError, match="exception traceback"):
        pair._native_receipt(
            native,
            task="desktop/task",
            arm="geode",
            model="geode-gpt-5.4",
            effort="high",
            timeout=1200,
        )


def test_native_receipt_accepts_the_geode_timeout_failure_class(tmp_path: Path) -> None:
    native = tmp_path / "native"
    _write_native(
        native,
        task="papers/author_folders",
        arm="geode",
        model="geode-gpt-5.4",
        effort="high",
        timeout=1200,
        timed_out=True,
    )

    receipt = pair._native_receipt(
        native,
        task="papers/author_folders",
        arm="geode",
        model="geode-gpt-5.4",
        effort="high",
        timeout=1200,
    )

    assert receipt["verifier_pass"] is False
    assert receipt["agent_error_present"] is True

    meta_path = next(native.rglob("meta.json"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for invalid_error in (False, "codex exec exceeded MCPMark action deadline (1200s)"):
        meta["execution_result"]["error_message"] = invalid_error
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        with pytest.raises(pair.PairRunError, match="score-bearing failure class"):
            pair._native_receipt(
                native,
                task="papers/author_folders",
                arm="geode",
                model="geode-gpt-5.4",
                effort="high",
                timeout=1200,
            )


def test_tool_cap_receipt_rejects_a_different_effective_config(tmp_path: Path) -> None:
    native = tmp_path / "native"
    _write_native(
        native,
        task="legal_document/dispute_review",
        arm="geode",
        model="geode-gpt-5.4",
        effort="high",
        timeout=1200,
        max_tool_result_tokens=0,
    )

    with pytest.raises(pair.PairRunError, match="runtime configuration mismatch"):
        pair._native_receipt(
            native,
            task="legal_document/dispute_review",
            arm="geode",
            model="geode-gpt-5.4",
            effort="high",
            timeout=1200,
            expected_tool_cap=25_000,
            expected_tool_schema_sha256=_TOOL_SCHEMA_SHA256,
        )


def test_tool_cap_receipt_rejects_tool_schema_drift(tmp_path: Path) -> None:
    native = tmp_path / "native"
    _write_native(
        native,
        task="legal_document/dispute_review",
        arm="geode",
        model="geode-gpt-5.4",
        effort="high",
        timeout=1200,
        max_tool_result_tokens=25_000,
    )

    with pytest.raises(pair.PairRunError, match="tool schema mismatch"):
        pair._native_receipt(
            native,
            task="legal_document/dispute_review",
            arm="geode",
            model="geode-gpt-5.4",
            effort="high",
            timeout=1200,
            expected_tool_cap=25_000,
            expected_tool_schema_sha256="d" * 64,
        )


def test_native_receipt_rejects_a_summary_that_contradicts_the_verifier(tmp_path: Path) -> None:
    native = tmp_path / "native"
    _write_native(
        native,
        task="desktop/task",
        arm="geode",
        model="geode-gpt-5.4",
        effort="high",
        timeout=1200,
    )
    summary_path = next(native.rglob("summary.json"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["successful_tasks"] = 0
    summary["failed_tasks"] = 1
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(pair.PairRunError, match="exact one-task arm result"):
        pair._native_receipt(
            native,
            task="desktop/task",
            arm="geode",
            model="geode-gpt-5.4",
            effort="high",
            timeout=1200,
        )


def test_tool_cap_truncation_is_reconstructed_from_the_raw_log(tmp_path: Path) -> None:
    path = tmp_path / "execution.log"
    path.write_text(
        json.dumps([{"result": {"content": [{"type": "text", "text": "x" * 100_100}]}}]),
        encoding="utf-8",
    )

    assert pair._truncation_count(path, max_tokens=25_000) == 1
    assert pair._truncation_count(path, max_tokens=0) == 0


def test_tool_cap_truncation_accepts_error_dicts_and_ignores_server_flags(
    tmp_path: Path,
) -> None:
    path = tmp_path / "execution.log"
    path.write_text(
        json.dumps([{"result": {"error": "caught"}}, {"result": {"_truncated": True}}]),
        encoding="utf-8",
    )

    assert pair._truncation_count(path, max_tokens=25_000) == 0
    assert pair._truncation_count(path, max_tokens=0) == 0


def test_tool_cap_truncation_rejects_a_non_dict_result(tmp_path: Path) -> None:
    path = tmp_path / "execution.log"
    path.write_text(json.dumps([{"result": "unexpected"}]), encoding="utf-8")

    with pytest.raises(pair.PairRunError, match="unknown tool-result shape"):
        pair._truncation_count(path, max_tokens=25_000)


def test_tool_cap_truncation_rejects_a_saturated_tool_log(tmp_path: Path) -> None:
    path = tmp_path / "execution.log"
    path.write_text(
        json.dumps([{"result": {}}] * pair.ToolCallProcessor.MAX_TOOL_LOG_ENTRIES),
        encoding="utf-8",
    )

    with pytest.raises(pair.PairRunError, match="retention cap"):
        pair._truncation_count(path, max_tokens=25_000)


def test_pair_runner_refuses_an_existing_attempt_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    monkeypatch.setattr(pair, "_validate_checkout", lambda _root: None)
    with pytest.raises(pair.PairRunError, match="must not exist"):
        pair.run_pair(
            run_spec_path=tmp_path / "run-spec.json",
            mcpmark_root=tmp_path / "mcpmark",
            output_dir=output,
            python=Path("python"),
        )


def test_pair_runner_freezes_the_validated_run_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = tmp_path / "prospective.json"
    spec_path.write_bytes(b'{"frozen":true}\n')
    output = tmp_path / "attempt"
    monkeypatch.setattr(pair, "_validate_checkout", lambda _root: None)
    monkeypatch.setattr(pair, "_discover_workload", lambda _root: ("desktop/first",))
    monkeypatch.setattr(pair, "_fixture_receipt", lambda *_args: _fixture())
    monkeypatch.setattr(
        pair,
        "_validate_pair_spec",
        lambda *_args, **_kwargs: {
            "run_id": "paired-test",
            "reproduction": {
                "execution": {"timeout_seconds": 1200},
                "model": {"label": "gpt-5.4", "route": "subscription", "reasoning": "high"},
                "geode": {"revision": "abc"},
                "harness": {"revision": "def"},
            },
        },
    )
    monkeypatch.setattr(pair, "_run_tasks", lambda **_kwargs: None)
    monkeypatch.setattr(pair, "_python_preflight", lambda *_args: {"dependency_check": "pass"})
    codex_cli = {
        "version": pair.CODEX_CLI_VERSION,
        "source_revision": pair.CODEX_CLI_SOURCE_REVISION,
        "executable_sha256": "e" * 64,
    }
    monkeypatch.setattr(
        pair,
        "_codex_cli_preflight",
        lambda *_args: (codex_cli, tmp_path / "codex"),
    )
    monkeypatch.setattr(pair, "_probe_filesystem_tool_schema", lambda *_args: _TOOL_SCHEMA_SHA256)

    pair.run_pair(
        run_spec_path=spec_path,
        mcpmark_root=tmp_path / "mcpmark",
        output_dir=output,
        python=Path("python"),
        profile=pair.PAIR_SMOKE_PROFILE,
        task="desktop/first",
    )

    assert (output / "run-spec.json").read_bytes() == spec_path.read_bytes()
    plan = json.loads((output / "runner-plan.json").read_text(encoding="utf-8"))
    assert plan["tool_schema_sha256"] == _TOOL_SCHEMA_SHA256
    assert plan["profile"] == pair.PAIR_SMOKE_PROFILE
    assert plan["workload_ids"] == ["desktop/first"]
    assert plan["codex_cli"] == codex_cli


def test_pair_runner_preflights_before_creating_output_or_running_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = tmp_path / "prospective.json"
    spec_path.write_bytes(b'{"frozen":true}\n')
    output = tmp_path / "attempt"
    monkeypatch.setattr(pair, "_validate_checkout", lambda _root: None)
    monkeypatch.setattr(pair, "_discover_workload", lambda _root: ("desktop/first",))
    monkeypatch.setattr(pair, "_fixture_receipt", lambda *_args: _fixture())
    monkeypatch.setattr(
        pair,
        "_validate_pair_spec",
        lambda *_args, **_kwargs: {
            "reproduction": {
                "execution": {"timeout_seconds": 1200},
                "model": {"label": "gpt-5.4", "route": "subscription", "reasoning": "high"},
            }
        },
    )
    monkeypatch.setattr(
        pair,
        "_python_preflight",
        lambda *_args: (_ for _ in ()).throw(pair.PairRunError("preflight failed")),
    )
    run_tasks_called = False

    def run_tasks(**_kwargs: object) -> None:
        nonlocal run_tasks_called
        run_tasks_called = True

    monkeypatch.setattr(pair, "_run_tasks", run_tasks)

    with pytest.raises(pair.PairRunError, match="preflight failed"):
        pair.run_pair(
            run_spec_path=spec_path,
            mcpmark_root=tmp_path / "mcpmark",
            output_dir=output,
            python=Path("python"),
        )

    assert not output.exists()
    assert run_tasks_called is False


def test_cli_preserves_the_selected_virtualenv_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "python-real"
    target.touch()
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(target)
    captured: dict[str, Path] = {}

    def run_pair(**kwargs: object) -> None:
        selected = kwargs["python"]
        assert isinstance(selected, Path)
        captured["python"] = selected

    monkeypatch.setattr(pair, "run_pair", run_pair)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_mcpmark_pair",
            "--run-spec",
            str(tmp_path / "run-spec.json"),
            "--mcpmark-root",
            str(tmp_path / "mcpmark"),
            "--output-dir",
            str(tmp_path / "output"),
            "--python",
            str(python),
        ],
    )

    pair.main()

    assert captured["python"] == python.absolute()
    assert captured["python"].is_symlink()


def test_append_event_flushes_with_fsync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(pair.os, "fsync", calls.append)
    path = tmp_path / "events.jsonl"
    pair._append_event(path, {"event": "started"})
    assert calls
    assert json.loads(path.read_text(encoding="utf-8")) == {"event": "started"}


def test_deadline_receipt_fails_closed_on_a_different_surface(tmp_path: Path) -> None:
    native = tmp_path / "native"
    _write_native(
        native,
        task="desktop/task",
        arm="geode",
        model="geode-gpt-5.4",
        effort="high",
        timeout=1200,
        timed_surface="loop_only",
    )
    path = next(native.rglob("execution.deadline.json"))
    with pytest.raises(pair.PairRunError, match="identity mismatch"):
        pair._deadline_receipt(path, arm="geode", timeout=1200)
