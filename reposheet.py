"""
Reposheet is a module for scanning GitHub repositories.
"""

import os
import re
import types
from typing import Any, Callable, List, Optional

import pandas as pd
from github import (Github, BadCredentialsException, UnknownObjectException,
    RateLimitExceededException)
from memoization import cached
from qgrid import show_grid
from tqdm.notebook import tqdm_notebook
from ipywidgets import Button, HBox, HTML, Layout, Output, Password, Text, VBox


def sparkline_svg(
        data: List[int],
        add_embed: bool = False,
        **params: dict,
    ) -> str:
    """Create a sparkline for given numerical ``data`` in SVG format.
    """
    width = params.get("width", len(data))
    height = params.get("height", 10)
    stroke = params.get("stroke", "#8cc665")
    weight = params.get("weight", 2)
    min_, max_ = min(data), max(data)
    if min_ != max_:
        points = " ".join(
            [f"{i / len(data) * width},{(max_ - val)/max_*height}"
                 for (i, val) in enumerate(data)]
        )
    else:
        points = " ".join([f"{i / len(data) * width},{height-1}" for (i, val) in enumerate(data)])
    style = f"fill: none; stroke: {stroke}; stroke-width: {weight}"
    svg = f"""<svg height="{height}" width="{width}"><polyline points="{points}" style="{style}" /></svg>"""
    return f"<embed>{svg}</embed>" if add_embed else svg


class GitHubRepoScanner:
    """A scanner for GitHub repositories.
    
    This scans repositories for organisations or users and collects meta-information
    about them in tabular form.
    """
    def __init__(self, g):
        self.g = g

    @cached
    def get_repo_attr(
            self,
            repo,
            name: str,
            total: bool=False,
            args: List=[],
            kwargs: dict={}
        ) -> Any:
        """Get value of some attribute with given name and cache it.

        If the ``name`` field resolves to a method of the ``repo`` object it will
        be called with the given parameters ``args`` and ``kwargs``.
        If ``total`` is ``True`` an additional attribute access for ``.totalCount``
        will be appended before returning the result.

        :param repo: Repository object.
        :param name: Attribute name.
        :param total: Boolean flag, ``True`` to append ``.totalCount``
            (default: ``False``).
        :param args: Parameter list to pass as positional parameters to the
            attribute value. 
        :param kwargs: Parameter dict to pass as named parameters to the
            attribute value.
        :return: The attribute value (most often a string or number).
        """
        thing = repo.__getattribute__(name)
        if type(thing) == types.MethodType:
            res = thing(*args, **kwargs)
            return res.totalCount if total else res
        else:
            return thing

    def scan_repos(
            self,
            org_name: Optional[str]=None,
            user_name: Optional[str]=None,
            owner_name: Optional[str]=None,
            repo_name_pat: Optional[str]=None,
            fields: Optional[List[str]]=None,
            callbacks: Optional[List[Callable]]=None,
            use_tqdm: bool=False
        ):
        """Iterate over all repos of some owner and yield dicts describing one repository.

        :param org_name: Organization name (must not be given together with ``user_name``).
        :param user_name: User name (must not be given together with ``org_name``).
        :param owner_name: User or organization name (must not be given together with
            ``user_name`` or ``org_name``).
        :param repo_name_pat: A regular expression to yield entries for matching repo
            names only.
        :param fields: A list of field (attribute) names to fetch for all repos.
        :param callbacks: A list of callables adding custom fields. A callable will be
            called with the following signature: ``my_callback(scanner, repo)``.
        :param use_tqdm: A flag to indicate using ``tqdm`` while iterating or not.
        :raises: ``UnknownObjectException`` if user/organization is not found.
        :return: A generator that yields dicts describing repositories.
        """
        assert len(list(filter(None, [org_name, user_name, owner_name]))) == 1
        
        if not owner_name:
            owner = self.g.get_organization(org_name) if org_name else self.g.get_user(user_name)
        else:
            try:
                owner = self.g.get_organization(owner_name)
            except UnknownObjectException:
                try:
                    owner = self.g.get_user(owner_name)
                except UnknownObjectException:
                    raise
        repos = sorted(owner.get_repos(), key=lambda r: r.name.lower())

        # ---------------- HACK !!!
        yield repos
        # ---------------- HACK !!!
        
        if repo_name_pat:
            repos = [r for r in repos if re.match(repo_name_pat, r.name)]
        fields = fields or \
            ("name private archived fork created_at "
             "issues contributors subscribers branches releases tags "
             "labels pulls downloads forks_count stargazers_count "
             "get_languages get_commits commit_activity").split()
        get = self.get_repo_attr
        for i, repo in enumerate(repos):
            entry = {}
            if "name" in fields:
                repo_name = get(repo, "name")
                url = f'https://github.com/{owner.login}/{repo_name}'
                entry["name"] = f'<a href="{url}">{repo_name}</a>'
            if "full_name" in fields:
                full_name = get(repo, "full_name")
                repo_name = full_name.split("/")[1]
                url = f'https://github.com/{owner.login}/{repo_name}'
                entry["full_name"] = f'<a href="{url}">{full_name}</a>'
            for name in "private archived fork".split():
                if name in fields:
                    entry[name] = "T" if get(repo, name) else "F"
            if "created_at" in fields:
                entry["created_at"] = get(repo, "created_at")
            # "last_modified": repo.last_modified,
            for key in ("issues contributors subscribers branches releases tags "
                        "labels pulls downloads").split():
                if key in fields:
                    entry[key] = get(repo, "get_" + key, total=True)
            if "forks_count" in fields:
                entry["forks_count"] = get(repo, "forks_count")
            if "stargazers_count" in fields:
                entry["stargazers_count"] = get(repo, "stargazers_count")
            if "get_languages" in fields:
                entry["get_languages"] = ",".join(sorted(get(repo, "get_languages").keys()))
            if "get_commits" in fields:
                try:
                    entry["get_commits"] = get(repo, "get_commits", total=True)
                except:
                    entry["get_commits"] = None
            if "commits_1y" in fields:
                res = get(repo, "get_stats_commit_activity")
                if res:
                    commit_activity = sum([act.total for act in res])
                    entry["commits_1y"] = sum([act.total for act in res])
                else:
                    entry["commits_1y"] = 0
            if "commit_activity" in fields:
                res = get(repo, "get_stats_commit_activity")
                if res:
                    commit_activity = [act.total for act in res]
                    entry["commit_activity"] = sparkline_svg(commit_activity, height=15, width=100)
                else:
                    entry["commit_activity"] = ""
            if callbacks:
                for cb in callbacks:
                    entry.update(cb(self, repo))
            yield entry
    

class ReposheetUI(VBox):
    """ReposheetUI returns stats about multiple code repositories.
    
    This will create an interactive spreadsheet-like overview of high-level
    key values for repositories of some user or organization.

    To do that it needs the repo URL and an API key for the repository hoster
    (for now GitHub). So far it works only for github.com, but support for
    gitlab.com is coming!
    """
    def __init__(self, url=None, token=None, regexpr=None, fields=None, callbacks=None):
        """Instantiate a UI controller.
        """
        super().__init__()

        self.fields = fields
        self.callbacks = callbacks or []
        
        # toolbar
        self.ht = HTML("<b>Host/Owner:</b>")
        self.tx_desc = "Repo owner URL, eg. https://github.com/python"
        self.tx = Text(url or "",
            placeholder=self.tx_desc,
            description_tooltip="Repo owner URL, press enter to scan!",
            layout=Layout(width="200px"))
        self.tx.on_submit(self.start_scan)
        tok_desc = "GitHub API Access Token"
        self.tok = Password(token,
            placeholder=tok_desc, description_tooltip=tok_desc,
            layout=Layout(width="175px"))
        self.tok.on_submit(self.start_scan)
        self.btn = Button(description="Scan", button_style="info",
            layout=Layout(width="100px"))
        self.btn.on_click(self.start_scan)
        rx_desc = "Regex to match repo names"
        self.rx = Text(regexpr,
            placeholder=rx_desc, description_tooltip=rx_desc,
            layout=Layout(width="60px"))
        self.rx.on_submit(self.start_scan)
        self.toolbar = HBox([
            self.ht, self.tx, self.tok, self.rx, self.btn
        ])

        # content area
        self.sx = HTML(layout=Layout(width="100pc"))
        self.tabout = VBox()
        self.pbout = Output()
        self.out = Output()
        self.cont = VBox([
            self.sx,
            self.tabout,
            self.pbout,
            self.out
        ])
        
        # entire area
        self.children = [
            self.toolbar,
            self.cont
        ]
        
        self.scanner = None


    def start_scan(self, widget):
        """Callback for the scan button or name text line.
        """
        self.sx.value = ""
        if not self.tx.value.startswith("github.com/") or not "/" in self.tx.value:
            self.sx.value = "Expected: github.com/&lt;owner&gt;"
            return

        # toolbar
        with self.out:    
            btn_desc = self.btn.description
            self.btn.description = "Scanning..."
            self.btn.disabled = True
            token = self.tok.value or None
            if self.scanner is None:
                self.scanner = GitHubRepoScanner(Github(token))
            fields = self.fields or ["name", "created_at", "fork", "contributors",
                "subscribers", "forks_count", "issues", "pulls", "stargazers_count",
                "get_commits", "commits_1y", "commit_activity"]
            repo_name_pat = self.rx.value
            owner_name = self.tx.value.split("/")[1]
            data = []
            df = pd.DataFrame(data, columns=fields)
            opts = {"enableColumnReorder": True}
            self.tab = show_grid(df, show_toolbar=False, grid_options=opts)
            kwargs = dict(
                owner_name=owner_name,
                repo_name_pat=repo_name_pat,
                fields=fields,
                callbacks=self.callbacks,
                use_tqdm=False
            )
            try:
                gen = self.scanner.scan_repos(**kwargs)
                repos = next(gen)
                num_repos = len(repos)
            except UnknownObjectException:
                self.sx.value = "Unknown Object"
            except RateLimitExceededException:
                self.sx.value = "Rate Limit Exceeded"
            except BadCredentialsException:
                self.sx.value = "Bad Credentials"
                        
        # progress bar
        with self.pbout:
            pb = tqdm_notebook(initial=0, total=num_repos)
        
        # table
        with self.out:
            try:
                for i, row in enumerate(gen):
                    if i == 0:
                        self.tabout.children = [self.tab]
                    # tab.add_row(row=row.items())  # not working
                    self.tab.df = self.tab.df.append(row, ignore_index=True)
                    pb.update(1)
                self.pbout.clear_output()
            except RateLimitExceededException:
                self.sx.value = "Rate Limit Exceeded"
                pb.close()
            except KeyboardInterrupt:
                pb.close()

        # toolbar
        self.btn.disabled = False
        self.btn.description = btn_desc
