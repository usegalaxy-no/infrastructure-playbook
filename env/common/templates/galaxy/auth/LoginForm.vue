<script setup lang="ts">
import axios from "axios";
import {
    BAlert,
    BButton,
    BCard,
    BCardBody,
    BCardFooter,
    BCardHeader,
    BEmbed,
    BForm,
} from "bootstrap-vue";
import { computed, ref } from "vue";
import { useRouter } from "vue-router/composables";

import localize from "@/utils/localization";
import { withPrefix } from "@/utils/redirect";
import { errorMessageAsString } from "@/utils/simple-error";

import NewUserConfirmation from "@/components/Login/NewUserConfirmation.vue";
import ExternalLogin from "@/components/User/ExternalIdentities/ExternalLogin.vue";

interface Props {
    sessionCsrfToken: string;
    redirect?: string;
    termsUrl?: string;
    welcomeUrl?: string;
    enableOidc?: boolean;
    showWelcomeWithLogin?: boolean;
    registrationWarningMessage?: string;
}

const props = defineProps<Props>();

const emit = defineEmits<{
    (e: "toggle-login"): void;
    (e: "set-redirect", url: string): void;
}>();

const router = useRouter();

const urlParams = new URLSearchParams(window.location.search);

const loading = ref(false);
const messageText = ref("");
const messageVariant = ref<"info" | "danger">("info");

const confirmURL = ref(urlParams.has("confirm") && urlParams.get("confirm") == "true");

function setRedirect(url: string) {
    localStorage.setItem("redirect_url", url);
}

function returnToLogin() {
    router.push("/login/start");
}
</script>

<template>
    <div class="container">
        <div class="row justify-content-md-center">

            <!-- LEFT INFO PANEL -->
            <div class="col">
                <h1>
                    Welcome to <b>UseGalaxy.no</b> - a data analysis platform for life science data
                </h1>

                <p style="margin-top:20px">
                    This service is maintained by Elixir Norway and is for users from both the academia and industry sectors.
                    Extensive use from the industrial sector will have to be charged based on CPU hours - This model is under construction.
                </p>

                <p>
                    The service can be accessed using FEIDE login if your institution is FEIDE connected to the NeLS portal.
                    Users from the industry sector and international research collaborators that don't have FEIDE access can apply for a NeLS ID.
                </p>

                <p>
                    Questions can be directed to our
                    <a href="https://elixir.no/helpdesk" target="_blank">helpdesk</a>.
                </p>

                <a href="https://nels.elixir.no" target="_blank">
                    <img src="/static/images/nels_logo_old.png" style="width:200px;margin-top:6px;margin-right:20px">
                </a>
                <a href="https://galaxyproject.org" target="_blank">
                    <img src="/static/images/galaxy_logo.png" style="width:160px;margin-top:6px;margin-right:20px">
                </a>
                <a href="https://elixir.no" target="_blank">
                    <img src="/static/images/elixir_no_logo.png" style="width:124px;margin-top:6px;">
                </a>
            </div>

            <!-- LOGIN PANEL -->
            <template v-if="!confirmURL">
                <div class="col col-lg-6">

                    <BAlert :show="!!messageText" :variant="messageVariant">
                        <span v-html="messageText" />
                    </BAlert>

                    <BForm id="login">
                        <BCard no-body>

                            <BCardHeader>
                                <span>{{ localize("Please log in with one of the options below") }}</span>
                            </BCardHeader>

                            <BCardBody>

                                <!-- INTERNAL LOGIN REMOVED -->

                                <!-- OIDC ONLY -->
                                <div v-if="enableOidc">
                                    <ExternalLogin login-page />
                                </div>

                            </BCardBody>

                            <BCardFooter>
                                Don't have a FEIDE account? Apply for a NeLS ID by first clicking on
                                "FEIDE or NeLS ID" above, then "Login with NeLS Identity" and finally
                                "Apply for a NeLS Account"
                            </BCardFooter>

                        </BCard>
                    </BForm>

                    <!-- Extra text -->
                    <p style="margin-top:30px">
                        Please acknowledge or cite Elixir Norway in any research that uses UseGalaxy.no
                        <br>
                        See the
                        <a href="https://nels-docs.readthedocs.io/en/latest/about.html#how-to-cite-us" target="_blank">
                            Elixir Norway wiki
                        </a>
                    </p>

                </div>
            </template>

            <template v-else>
                <NewUserConfirmation
                    :registration-warning-message="registrationWarningMessage"
                    :terms-url="termsUrl"
                    @setRedirect="setRedirect" />
            </template>

            <div v-if="showWelcomeWithLogin && props.welcomeUrl" class="col">
                <BEmbed type="iframe" :src="withPrefix(props.welcomeUrl)" aspect="1by1" />
            </div>

        </div>
    </div>
</template>

<style scoped lang="scss">
.card-body {
    overflow: visible;
}
</style>
