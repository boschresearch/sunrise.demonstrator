# Contributing to SUNRISE

## :warning: In Any Case

**Before opening an issue, opening a pull-request or contacting us:**
- Make sure that you are using the latest version of the repository
- Do a clean checkout of the repository
- Make sure what you are experiencing is reproducible (e.g. on another host system)
- Check if an issue with your topic already exists


## :question: Asking Questions

- Before asking a question, make sure you have read the documentation.
- If the question is not about our work itself (e.g. related to your environment setup): Search the internet.
- If your question is related to an existing issue, ask it there.

Otherwise: **:writing_hand: Create a new issue with the Label *question*.**


## :negative_squared_cross_mark: Reporting Bugs

*We constantly strive to improve our work, so we prioritize fixing bugs!*

In the best case, you can correct the error yourself and [contribute a fix](#-code-contributions) to the code base.

Otherwise: **:writing_hand: Create a new issue with the Label *bug*** and adhere to the following
- Explain the *expected behavior* and how the current implementation deviates from that
- Provide enough context and describe how to *reproduce the behavior*. If it cannot be reproduced, it cannot be fixed.
- For good bug reports you should isolate the problem and provide a minimal setup


## :incoming_envelope: Code Contributions

*Extensions, improvements and fixes are welcome contributions to the repository!*

To contribute to the code:
- Always make sure your work is based on the latest version of the repository. Otherwise it can require high merge effort and will probably be rejected.
- Create a fork of this repository, apply the changes there and create a pull-request to our code-base from your work
  - Add sufficient information to the pull request so the intention is clear
  - Link to an existing issue if available


A **pull-request** will be merged into the code-base, if:
- The contribution is in line with the project objectives
- The code meets our expectations for code quality
- The contribution does not break any functionality
- You adhere the Developer Certificate of Origin (DCO) by signing commits


### Sign Your work
With the sign-off text in the commit message you explicitly acknowledge the [Developer Certificate of Origin (DCO)](https://wiki.linuxfoundation.org/dco). The following line must be appended to the commit message:
```
Signed-off-by: Full Name <email>
```

If you have set your `user.name` and `user.email` git config parameters, you can automatically sign your commit by running with the `-s` option: `git commit -s -m 'Your commit message'`.

```
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.


Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```
